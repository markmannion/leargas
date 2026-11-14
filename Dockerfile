# Backend image for a Hugging Face Docker Space (also runs on Render, Railway or Fly.io).
# The dataset is not in the image: deploy/start.sh downloads it at startup with HF_TOKEN.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 git \
    && rm -rf /var/lib/apt/lists/*

# Spaces run as uid 1000.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH PYTHONUNBUFFERED=1
WORKDIR /home/user/app

COPY --chown=user backend/requirements*.txt backend/
RUN pip install --no-cache-dir --user \
      -r backend/requirements-dxf.txt -r backend/requirements-ifc.txt -r backend/requirements-sheet.txt \
      "huggingface_hub[cli]>=0.34"

COPY --chown=user backend backend
COPY --chown=user model model
COPY --chown=user contracts contracts
COPY --chown=user deploy/start.sh deploy/start.sh

EXPOSE 7860
CMD ["bash", "deploy/start.sh"]
