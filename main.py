import os, uuid, re, logging
from pathlib import Path
from typing import List
from fastapi import FastAPI, UploadFile, File, HTTPException,status
from fastapi.staticfiles import StaticFiles
import boto3
from io import BytesIO
from pypdf import PdfReader, PdfWriter
from typing import Optional
from PIL import Image, UnidentifiedImageError


logging.basicConfig(level = logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

app = FastAPI()

S3_BUCKET = os.getenv("S3_BUCKET")
AWS_REGION = os.getenv("AWS_REGION")

if not S3_BUCKET:
    raise RuntimeError("S3_BUCKET env is missing")

s3 = boto3.client(
    "s3",
    region_name=AWS_REGION,
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY")
)

ALLOWED_EXT = {".pdf", ".jpg", ".jpeg", ".png"}
MAX_PAGES = 10

def sanitize_filename(name: str) -> str:
    base = os.path.basename(name)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", base)
    return (safe or "file")[:80]

def build_input_key(batch_id: str, filename: str) -> str:
    return f"jobs/{batch_id}/inputs/{uuid.uuid4().hex[:8]}_{sanitize_filename(filename)}"

@app.get("/health")
def health(): return {"status": "ok"}


@app.post("/merge/from-upload", status_code=status.HTTP_201_CREATED)
async def merge_from_upload(
    files: List[UploadFile] = File(...),
    filename: Optional[str] = "merged.pdf",
    expires_in: int = 900,
):
    if not files:
        raise HTTPException(status_code = status.HTTP_400_BAD_REQUEST, detail = "Please select at least a file")

    total_pages = 0
    errors = [] 

    writer= PdfWriter()
    try:
        for f in files:
            name = os.path.basename(f.filename or "")
            ext = Path(name).suffix.lower().strip()  

            if ext not in ALLOWED_EXT:
                errors.append({"file": name, "reason": "Unsupported media type (%s)" % ext})
                continue

            try:
                data = await f.read()
                size = len(data) if data else 0
                logging.info("read: %s bytes=%d", name, size)
                if not data:
                    errors.append({"file": name, "reason": "Empty file"})
                    continue


                if ext == ".pdf":
                    try:
                        reader = PdfReader(BytesIO(data))
                    except Exception as e:
                        errors.append({"file": name, "reason": "Could not read PDF: %s" % str(e)})
                        continue
                    

                    pages = len(reader.pages)
                    logging.info("parsed pdf: %s pages=%d", name, pages)
                    if pages == 0:
                        errors.append({"file": name, "reason": "PDF has zero pages"})
                        continue
                    if total_pages + pages > MAX_PAGES:
                        raise HTTPException(
                            status.HTTP_400_BAD_REQUEST,
                            detail="Exceeds total page limit: %s "% MAX_PAGES
                        )

                    for p in reader.pages:
                        writer.add_page(p)
                        total_pages += pages
                        logging.info("added pdf: %s (+%d) total=%d", name, pages, total_pages)


                else:
                    if total_pages + 1 > MAX_PAGES:
                        raise HTTPException(
                            status.HTTP_400_BAD_REQUEST,
                            detail="Exceeds total page limit: %s  "% MAX_PAGES
                        )
                    try:
                        img = Image.open(BytesIO(data))
                        if img.mode in ("RGBA", "LA"):
                            bg = Image.new("RGB", img.size, (255, 255, 255))
                            bg.paste(img, mask=img.split()[-1])
                            img = bg
                        else:
                            img = img.convert("RGB")

                        pdf_buf = BytesIO()
                        img.save(pdf_buf, format="PDF")
                        pdf_buf.seek(0)

                        pdf_reader = PdfReader(pdf_buf)
                        writer.add_page(pdf_reader.pages[0])
                        total_pages += 1

                    except UnidentifiedImageError:
                        errors.append({"file": name, "reason": "Image not detected or corrupted"})
                        continue

            except Exception as e:
                errors.append({"file": name, "reason": str(e)})
                continue
        logging.info("total pages: %s " % total_pages)
        if total_pages == 0:
            raise HTTPException(
                status_code=400,
                detail="There are no valid pages to merge.")

        out = BytesIO()
        #merger.write(out)
        writer.write(out)
        out.seek(0)

    finally:
        try:
            writer.close()
        except Exception:
            pass

    batch_id = uuid.uuid4().hex[:12]
    safe = sanitize_filename(filename or "merged.pdf")
    out_key = "jobs/%s/merged/%s_%s" % (batch_id, uuid.uuid4().hex[:8], safe)

    s3.upload_fileobj(out, S3_BUCKET, out_key, ExtraArgs={"ContentType": "application/pdf"})

    ttl = int(expires_in)
    if ttl < 60:
        ttl = 60
    if ttl > 7*24*3600:
        ttl = 7*24*3600

    disposition = 'attachment; filename="%s"' % safe
    params = {
        "Bucket": S3_BUCKET,
        "Key": out_key,
        "ResponseContentType": "application/pdf",
        "ResponseContentDisposition": disposition,
    }
    url = s3.generate_presigned_url("get_object", Params=params, ExpiresIn=ttl)

    return {
        "ok": True,
        "url": url,
        "batch_id": batch_id,
        "key": out_key,
        "total_pages": total_pages,
        "errors": errors,
    }

app.mount("/", StaticFiles(directory="static", html=True), name="static")