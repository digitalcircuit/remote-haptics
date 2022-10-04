### Remaining cleanup steps

* [ ] Document optional use of [AppDirs to store config in default platform locations](https://pypi.org/project/appdirs/ ) (e.g. [XDG Base Directory Specification for Linux](https://specifications.freedesktop.org/basedir-spec/basedir-spec-latest.html ))
* [ ] Include [Impulse source from Actinic](https://github.com/digitalcircuit/actinic/tree/main/Actinic/Audio/impulse ) (submodule?) and build `impulse-print`
  * Only `impulse-print` is needed by `remote_haptics/haptics_audio.py`
* [ ] Make a `README.md` file
* [ ] Clean up code with documentation
* [ ] Add tests
* [ ] Add authentication from client to server (not just server to client verifying certificate)
