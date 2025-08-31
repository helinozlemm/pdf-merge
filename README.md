pdf-merge

A small web service that merges PDFs and images (JPG/PNG) entirely in memory. You upload files in the browser; the API combines them and uploads only the merged PDF to Amazon S3, then returns a pre-signed download link. Original files aren’t stored, and a simple total-page limit keeps requests fast and safe.
Tech: Python 3.11, FastAPI, pypdf, Pillow, boto3 (AWS S3), Uvicorn, Docker, vanilla HTML/JS
