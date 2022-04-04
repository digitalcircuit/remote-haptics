# Device `udev` rules

## How to use?

Run the setup script from the parent folder (above this one):
```
./../setup-device-support.sh install
```

Or just copy the `*.rules` files into `/etc/udev/rules.d/` and run `sudo udevadm control --reload-rules && sudo udevadm trigger`.

## Undoing changes

```
./../setup-device-support.sh remove
```

*Note: this only works if the names and contents of the `.rules` files haven't changed.*
