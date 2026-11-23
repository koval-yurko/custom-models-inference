"""The bucket layout. gs://<project_id>-stt-audio/files/<id>/
  audio                              the uploaded audio
  meta.json                          name, mime type, size, created (also as object metadata, for the file list)
  versions/<version_id>.json         1 transcript version (never replaced)
  versions/<version_id>.names.json   the speaker names of that version (replaced on change)
  reference.json                     the correct transcript of the file (replaced on change)
"""
import re

ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
VERSION_RE = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{4}$")
SPEAKER_RE = re.compile(r"^spk_\d{1,2}$")
NAMES = ".names.json"  # files/<id>/versions/<version_id>.names.json, next to the version JSON
REFERENCE = "reference.json"  # files/<id>/reference.json
