FROM pytorch/pytorch:2.7.1-cuda12.6-cudnn9-runtime

RUN apt-get update && apt-get install -y --no-install-recommends git libgl1 libglib2.0-0 wget && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY requirements.txt requirements-gpu.txt ./
# SAM 3 needs Python 3.12+; this base image's Python must satisfy that (check `python --version`).
RUN pip install --no-cache-dir -r requirements.txt && pip install --no-cache-dir -r requirements-gpu.txt
COPY . .
ENV WEB_ASSETS_DIR=/srv/web
# Weights come from Hugging Face on first start: pass HF_TOKEN, or mount sam3.pt and set SAM3_CHECKPOINT.
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
