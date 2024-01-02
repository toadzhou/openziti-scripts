SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd $SCRIPT_DIR

source ./zrok.install.env
source $HOME/.ziti/quickstart/$(hostname)/$(hostname).env

sudo apt install nginx -y

sudo tee /etc/nginx/nginx.conf > /dev/null << HERE
events {
}
http {
  server {
      listen              ${ZROK_NGINX_PORT} ssl;
      server_name         ${ZROK_API_ADDRESS};
      ssl_certificate     ${LE_CHAIN};
      ssl_certificate_key ${LE_KEY};
      ssl_protocols       TLSv1.2;
      ssl_ciphers         HIGH:!aNULL:!MD5;

      location / {
        proxy_pass      http://127.0.0.1:${ZROK_CTRL_PORT};
        error_log       /var/log/nginx/zrok-controller.log;
      }
  }

  server {
      listen              ${ZROK_NGINX_PORT} ssl;
      server_name         *.${WILDCARD_DNS};
      ssl_certificate     ${LE_CHAIN};
      ssl_certificate_key ${LE_KEY};
      ssl_protocols       TLSv1.2;
      ssl_ciphers         HIGH:!aNULL:!MD5;

      location / {
        proxy_pass       http://127.0.0.1:${ZROK_FRONTEND_PORT};
        proxy_set_header Host \$host;
        error_log        /var/log/nginx/zrok-frontend.log;
        proxy_busy_buffers_size   512k;
        proxy_buffers    4 512k;
        proxy_buffer_size   256k;
      }
  }

  server {
      listen              8448 ssl;
      server_name         ${ZROK_API_ADDRESS};
      ssl_certificate     ${LE_CHAIN};
      ssl_certificate_key ${LE_KEY};
      ssl_protocols       TLSv1.2;
      ssl_ciphers         HIGH:!aNULL:!MD5;

      location / {
        proxy_pass       http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        error_log        /var/log/nginx/docker-test.log;
        proxy_busy_buffers_size   512k;
        proxy_buffers    4 512k;
        proxy_buffer_size   256k;
      }
  }
}
HERE

sudo nginx -t
sudo systemctl restart nginx


mkdir -p $ZROK_ROOT/bin
cd $ZROK_ROOT/bin

#xxx left in case break ZROK_VERSION=0.3.4
wget https://github.com/openziti/zrok/releases/download/v${ZROK_VERSION}/zrok_${ZROK_VERSION}_linux_amd64.tar.gz
tar zxvf zrok_${ZROK_VERSION}_linux_amd64.tar.gz

cat > $ZROK_ROOT/ctrl.yml << HERE
v: 3
admin:
  secrets:
    -               $ZROK_ADMIN_PWD
  tou_link:         '<a href="https://openziti.io" target="_">Terms and Conditions</a>'
endpoint:
  host:             0.0.0.0
  port:             $ZROK_CTRL_PORT
store:
  path:             zrok.db
  type:             sqlite3
ziti:
  api_endpoint:     "https://${ZITI_CTRL_EDGE_ADVERTISED_ADDRESS}:${ZITI_CTRL_EDGE_ADVERTISED_PORT}"
  username:         "${ZITI_USER}"
  password:         "${ZITI_PWD}"
invites:
  invites_open:     true
passwords:
  length:           4 
  require_capital:  false
  require_numeric:  true
  require_special:  false
  valid_special_characters: "\\"\\\\\`'''~!@#$%^&*()[],./"
HERE

zrok admin bootstrap $ZROK_ROOT/ctrl.yml 2>&1 | tee /tmp/zrok.admin.bootstrap.output
#zrokfe=$(grep "zrok admin create" /tmp/zrok.admin.bootstrap.output | cut -d ";" -f1 | cut -d \' -f2)
ZROK_FRONTEND_ID=$(grep "zrok admin create" /tmp/zrok.admin.bootstrap.output | cut -d ";" -f1 | cut -d \' -f2)
#echo ""
#echo "look at the output above. find the line that looks like this:"
#echo " "
#echo "... ... missing public frontend for ziti id 'xxxxxxxxxx'; please use 'zrok admin create frontend..."
#echo " "
#echo -n "copy and paste the token from that line here and press [enter]: ${zrokfe}"
#read ZROK_FRONTEND_ID

echo "using ZROK_FRONTEND_ID: ${ZROK_FRONTEND_ID}"

sudo tee /etc/systemd/system/zrok-controller.service > /dev/null << HERE
[Unit]
Description=zrok-controller
After=network.target

[Service]
User=root
WorkingDirectory=$ZROK_ROOT
ExecStart="$ZROK_ROOT/bin/zrok" controller "$ZROK_ROOT/ctrl.yml"
Restart=always
RestartSec=2
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
HERE

sudo systemctl daemon-reload
sudo systemctl enable --now zrok-controller

echo "sleeping while the controller starts..."
sleep 3

zrok config set apiEndpoint https://127.0.0.1:${ZROK_CTRL_PORT}

zrok admin create frontend ${ZROK_FRONTEND_ID} public https://{token}.${WILDCARD_DNS}:${ZROK_NGINX_PORT}


cat > $ZROK_ROOT/http-frontend.yml << HERE
host_match: ${WILDCARD_DNS}
address: 0.0.0.0:${ZROK_FRONTEND_PORT}
HERE

sudo tee /etc/systemd/system/zrok-frontend.service > /dev/null << HERE
[Unit]
Description=zrok-frontend
After=network.target

[Service]
User=root
WorkingDirectory=$ZROK_ROOT
ExecStart="$ZROK_ROOT/bin/zrok" access public "$ZROK_ROOT/http-frontend.yml"
Restart=always
RestartSec=2
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
HERE

sudo systemctl daemon-reload
sudo systemctl enable --now zrok-frontend

#echo " "
#echo "You should now be able to issue a \`zrok invite\` command to invite yourself to your self-hosted zrok"
#echo " "
#echo "  zrok invite"
#echo " "
#echo "You probably won't have an email server configured so after running zrok invite, you'll need to"
#echo "inspect the zrok-controller log for the token to use. In a separate terminal look at the log using"
#echo "journalctl:"
#echo ""
#echo "  journalctl --no-pager -u zrok-controller -n 100 | grep \"has registration token\""
#echo " "
#echo " "
#echo "After you get the invite token, you can then go to:"
#echo ""
#echo "  https://${ZROK_API_ADDRESS}:${ZROK_NGINX_PORT}/register/\${invite-token-here}"
echo " "
echo "Inviting the first zrok user now!"
echo " "
zrok invite

sleep 1

#journalctl --no-pager -u zrok-controller -n 100 | grep "has registration token"
echo " "
echo "now register by going to: https://${ZROK_API_ADDRESS}:${ZROK_NGINX_PORT}/register/$(journalctl --no-pager -u zrok-controller -n 100 | grep "has registration token" | tail -1 | cut -d ":" -f4-100 | jq .msg | cut -d \' -f4)"
echo " "
