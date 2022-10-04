#!/bin/sh

# Valid for 10 years
# For private use - expected to directly send new certificate to all involved users
CERT_VALID_DAYS="$((10 * 365))"

CERT_CONFIG_FILE="certs-config.cnf"
CERT_CONFIG_EXAMPLE_FILE="certs-config.example.cnf"

CERT_FILE="server.cert"
CERT_KEY="server.key"

# Inspect with...
# openssl x509 -in server.cert -text -noout

# See https://stackoverflow.com/questions/29436275/how-to-prompt-for-yes-or-no-in-bash
yes_or_no ()
{
	while true; do
		read -p "$* [y/n]: " yn
		case $yn in
			[Yy]*) return 0  ;;
			[Nn]*) echo "Aborted" ; return  1 ;;
		esac
	done
}

if [ ! -f "$CERT_CONFIG_FILE" ]; then
	echo "You need to set up your certificate configuration first." >&2
	echo "Copy '$CERT_CONFIG_EXAMPLE_FILE' to '$CERT_CONFIG_FILE' and edit that." >&2
	exit 1
fi

if [ -f "$CERT_FILE" ] || [ -f "$CERT_KEY" ]; then
	if yes_or_no "/!\ Key already exists!  Overwrite private key?"; then
		# Make backup copy
		mv "$CERT_FILE" "$CERT_FILE.bak"
		mv "$CERT_KEY" "$CERT_KEY.bak"
	else
		exit 1
	fi
fi

#openssl req -x509 -newkey rsa:2048 -keyout server.key -nodes -out server.cert -sha256 -days "$CERT_VALID_DAYS"
#openssl req -x509 -newkey rsa:4096 -keyout "$CERT_KEY" -nodes -out "$CERT_FILE" -config generate-certs-config.cnf -days "$CERT_VALID_DAYS"
openssl req -x509 -newkey rsa:4096 -keyout "$CERT_KEY" -nodes -out "$CERT_FILE" -config certs-config.cnf -days "$CERT_VALID_DAYS"

# Try to find XDG path
DATA_DIR=${XDG_DATA_HOME:-$HOME/.local/share}
if command -v systemd-path >/dev/null; then
    DATA_DIR="$(systemd-path user-shared)"
fi
DATA_CERT_DIR="$DATA_DIR/RemoteHaptics/certs/"
echo "------------"
echo "[i] To use this certificate and key by default, move '$CERT_FILE' and '$CERT_KEY' inside"
echo "    '$DATA_CERT_DIR'"
if yes_or_no "Move cert/key inside default RemoteHaptics folder?"; then
	if [ -f "$DATA_CERT_DIR/$CERT_FILE" ] || [ -f "$DATA_CERT_DIR/$CERT_KEY" ]; then
		if yes_or_no "/!\ Key already exists!  Overwrite private key?"; then
			# Make backup copy
			mv "$DATA_CERT_DIR/$CERT_FILE" "$DATA_CERT_DIR/$CERT_FILE.bak"
			mv "$DATA_CERT_DIR/$CERT_KEY" "$DATA_CERT_DIR/$CERT_KEY.bak"
		else
			exit 1
		fi
	fi
	mkdir --parents "$DATA_CERT_DIR"
	mv "$CERT_FILE" "$DATA_CERT_DIR/$CERT_FILE"
	mv "$CERT_KEY" "$DATA_CERT_DIR/$CERT_KEY"
	echo "Certificate and key moved!"
fi
