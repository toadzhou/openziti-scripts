from datetime import datetime
import socket
import json
import ssl
import sys
from OpenSSL import crypto
import requests
from concurrent.futures import ThreadPoolExecutor
from requests.packages.urllib3.exceptions import InsecureRequestWarning

# Suppress only the InsecureRequestWarning from urllib3 needed for SSL warnings
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)


def connect_and_get_certificate_chain(host, port, timeout=3):
    # Create a socket and set the timeout
    sock = socket.create_connection((host, port), timeout)

    # Wrap the socket with SSL/TLS without verifying the certificate
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    ssl_sock = context.wrap_socket(sock, server_hostname=host)

    # Get the peer certificate (including the chain)
    try:
        cert_chain = ssl_sock.getpeercert(True)
        return cert_chain
    except ssl.SSLError as e:
        print(f"Error retrieving certificate chain: {e}")
    finally:
        # Close the connection
        ssl_sock.close()


def subject_or_issuer_contain_ziti_cert(cert_bytes):
    certificate = crypto.load_certificate(crypto.FILETYPE_ASN1, cert_bytes)

    subject = certificate.get_subject().get_components()
    issuer = certificate.get_issuer().get_components()

    # Convert bytes to strings
    subject_str = {k.decode(): v.decode() for k, v in subject}
    issuer_str = {k.decode(): v.decode() for k, v in issuer}

    # print("Subject:", subject_str)
    # print("Issuer:", issuer_str)

    subject = certificate.get_subject()
    issuer = certificate.get_issuer()
    return (any("ziti" in value.lower() for value in subject_str.values()) or
            any("ziti" in value.lower() for value in issuer_str.values()))

    # print("Subject:", subject)
    # print("Issuer:", issuer)

    # Extract and print Subject Alternative Names (SANs)
    san_list = []
    # for i in range(certificate.get_extension_count()):
    #    ext = certificate.get_extension(i)
    #    if 'subjectAltName' in ext.get_short_name().decode('utf-8'):
    #        san_list = [s.strip() for s in str(ext).split(",")]
    #        break

    # if san_list:
    #    # print("Subject Alternative Names (SANs):")
    #    for san in san_list:
    #        print(f"- {san}")


def enumerate_sans(ip, port, timeout=3):
    try:
        certificate_chain = connect_and_get_certificate_chain(ip, port, 3)
        if certificate_chain:
            # print("Peer certificate (including chain):")
            certificate = crypto.load_certificate(crypto.FILETYPE_ASN1, certificate_chain)

            subject = certificate.get_subject().get_components()
            issuer = certificate.get_issuer().get_components()

            # # Convert bytes to strings
            # subject_str = {k.decode(): v.decode() for k, v in subject}
            # issuer_str = {k.decode(): v.decode() for k, v in issuer}
            # print("Subject:", subject_str)
            # print("Issuer:", issuer_str)
            #
            # subject = certificate.get_subject()
            # issuer = certificate.get_issuer()
            # print("Subject:", subject)
            # print("Issuer:", issuer)

            # Extract and print Subject Alternative Names (SANs)
            san_list = []
            for i in range(certificate.get_extension_count()):
                ext = certificate.get_extension(i)
                if 'subjectAltName' in ext.get_short_name().decode('utf-8'):
                    return ext
                    #san_list = [s.strip() for s in str(ext).split(",")]
                    #break

            # if san_list:
            #     # print("Subject Alternative Names (SANs):")
            #     for san in san_list:
            #         print(f"- {san}")
        else:
            print("no cert chain?")

    except socket.error as e:
        print(f"Socket error: {e}")
    except Exception as e:
        print(f"Errobr: {ip}:{port} - {e}")


def subject_or_issuer_contain_ziti(ip, port, timeout=3):
    try:
        certificate_chain = connect_and_get_certificate_chain(ip, port, 3)
        if certificate_chain:
            # print("Peer certificate (including chain):")
            return subject_or_issuer_contain_ziti_cert(certificate_chain)
    except socket.error as e:
        print(f"Socket error: {e}")
    except Exception as e:
        print(f"Errobr: {e}")
    return False


def print_certificate_info2(ip, port, timeout=3):
    try:
        certificate_chain = connect_and_get_certificate_chain(ip, port, 3)
        if certificate_chain:
            print("Peer certificate (including chain):")
            subject_or_issuer_contain_ziti_cert(certificate_chain)
    except socket.error as e:
        print(f"Socket error: {e}")
    except Exception as e:
        print(f"Errobr: {e}")

    try:
        result = check_if_https_server(ip, port, 3)
        print(f"{ip}:{port}\t{result}")

    except Exception as e:
        print(f"Errora: {e}")


def check_alpn(ip, port, timeout):
    if port == 22:
        return "Skipping\tSSH Port 22"  # Skip port 22

    alpn_protocols = ["ziti-ctrl", "ziti-link", "ziti-edge"]

    context = ssl.create_default_context()
    context.set_alpn_protocols(alpn_protocols)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    try:
        with socket.create_connection((ip, port), timeout=timeout) as sock:
            with context.wrap_socket(sock, server_hostname=ip) as ssock:
                negotiated_protocol = ssock.selected_alpn_protocol()
                if negotiated_protocol:
                    if negotiated_protocol == "ziti-ctrl":
                        return f"ALPN\t{negotiated_protocol} - control plane"
                    if negotiated_protocol == "ziti-link":
                        return f"ALPN\t{negotiated_protocol} - link listener"
                    if negotiated_protocol == "ziti-edge":
                        return f"ALPN\t{negotiated_protocol} - data plane"
                    return f"ALPN\t{negotiated_protocol} but not matched?"
                else:
                    if subject_or_issuer_contain_ziti(ip, port, timeout):
                        return f"no ALPN\tlikely older ziti-router"
                    else:
                        return f"no ALPN"
    except ConnectionRefusedError as e:
        return f"Conn Refused\t{e}"
    except socket.timeout as e:
        return f"Conn Timeout\t{e}"
    except (ssl.SSLError, socket.error) as e:
        if "WRONG_VERSION_NUMBER" in str(e):
            return f"Not TLS\t{e}"
        else:
            return f"SSLError\t{e}"


def check_if_https_server(ip, port, timeout=5):
    url = f"https://{ip}:{port}"

    try:
        response = requests.get(url, timeout=timeout, allow_redirects=True, verify=False)

        # Check if it's an HTTPS server
        headers = response.headers
        body = response.text.lower()

        if any(k.lower() == 'server' and v.lower().startswith('ziti-controller') for k, v in headers.items()):
            return f"HTTP\tziti-controller REST API"

        if "ziti login" in body:
            return f"HTTP\tziti-admin-console matched: ziti login"
        if "ziti console" in body:
            return f"HTTP\tziti-admin-console matched: ziti console"

        return f"HTTP\tnon-ziti-related"

    except requests.RequestException as e:
        return check_alpn(ip, port, 5)


def process_censys_hit(hit):
    ip = hit["ip"]
    loc = hit["location"]
    country = loc["country"]
    city = loc["city"]
    latitude = loc["coordinates"]["latitude"]
    longitude = loc["coordinates"]["longitude"]

    lines = []
    for service in hit["services"]:
        port = service["port"]
        result = check_if_https_server(ip, port, 3)
        sans = enumerate_sans(ip, port, 3)
        line = f"{ip}\t{port}\t{result}\t{country}\t{city}\t{latitude}\t{longitude}\t{sans}"
        lines.append(line)
        # print(f"line appended: {line}")

    print(f"completed processing ip: {ip}")
    return lines


def process_censys_json(json_data):
    data = json.loads(json_data)

    with ThreadPoolExecutor(max_workers=128) as executor:
        # Process hits in parallel and collect the results
        results = list(executor.map(process_censys_hit, data["result"]["hits"]))

    return results


if __name__ == "__main__":
    # enumerate_sans("35.234.69.11", "30250", 5)
    # exit(1)
    current_date = datetime.now().strftime("%Y-%m-%d")
    try:
        filename = sys.argv[1]
        with open(filename + ".json", 'r') as file:
            with ThreadPoolExecutor(max_workers=16) as executor:
                # Process lines in parallel and collect the results
                results = list(executor.map(process_censys_json, file))

        # Now that you have all the results, you can print them without interleaving
        print("==============================================")
        with open(filename + ".results.txt", 'w') as outf:
            for outer_array in results:
                for middle_array in outer_array:
                    print("\n".join(middle_array), file=outf)

    except KeyboardInterrupt:
        print("exiting...")
