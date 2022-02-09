import debugpy


def debug(wait=True):
    """Starts the debugpy server.

    In your code, add:
    ```
    from qfieldcloud.utils import debug
    debug()
    ```

    In VSCode, add the following launch configuration, then connect with F5:
    ```
    {
        "name": "QFieldCloud - Remote attach",
        "type": "python",
        "request": "attach",
        "connect": {"host": "localhost", "port": 5678},
        "pathMappings": [{
            "localRoot": "${workspaceFolder}/docker-app/qfieldcloud",
            "remoteRoot": "/usr/src/app/qfieldcloud"
        }]
    }
    ```
    """

    print("Starting debugging server... 🐛")
    debugpy.listen(("0.0.0.0", 5678))
    if wait:
        print("Waiting for debugger to connect... 🕰️")
        debugpy.wait_for_client()
