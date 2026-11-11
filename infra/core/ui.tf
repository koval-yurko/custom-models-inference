# Bucket for the static test UI (ui/). Anyone can read the files: they are a static React app and
# models.json (gateway URLs and model features). No secret goes here. The API key stays in the browser.
# scripts/ui-deploy.py builds the app, writes models.json and uploads both.

resource "google_storage_bucket" "ui" {
  project                     = var.project_id
  name                        = "${var.project_id}-ui"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "inherited"
  force_destroy               = true # only build output is in it; ui-deploy.py can upload it again

  depends_on = [google_project_service.apis]
}

# legacyObjectReader gives only storage.objects.get: allUsers can read a file, but cannot list or write.
resource "google_storage_bucket_iam_member" "ui_public_read" {
  bucket = google_storage_bucket.ui.name
  role   = "roles/storage.legacyObjectReader"
  member = "allUsers"
}
