# Bambu Lab Cloud API Reference

## Authentication
Login with Bambu Lab account email + password → receive access token.

## Python SDK: bambulab (PyPI: bambu-lab-cloud-api)

```python
from bambulab import BambuClient, BambuAuthenticator

auth = BambuAuthenticator()
token = auth.login(email, password)
client = BambuClient(token=token)
```

## Key Methods (BambuClient)
| Method | Description |
|--------|-------------|
| `get_devices()` | List all registered printers |
| `get_device_info(dev_id)` | Printer details |
| `get_print_status(dev_id)` | Current print status |
| `get_ams_filaments(dev_id)` | AMS slot info |
| `get_camera_urls(dev_id)` | Camera stream URLs |
| `get_cloud_files(dev_id)` | Files on cloud storage |
| `start_cloud_print(dev_id, file)` | Start a print job |
| `get_tasks(dev_id)` | Print task history |

## Sources
- https://pypi.org/project/bambu-lab-cloud-api/
- https://github.com/coelacant1/Bambu-Lab-Cloud-API
