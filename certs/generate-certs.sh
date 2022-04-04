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
