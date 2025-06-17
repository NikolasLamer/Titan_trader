# Dockerfile

# 1. Use an official, slim Python runtime as a parent image
FROM python:3.11-slim

# 2. Set environment variables for Python
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# 3. Set the working directory inside the container
WORKDIR /app

# 4. Copy and install dependencies
# This leverages Docker's layer caching for faster builds.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy the application code into the container
COPY . .

# 6. Expose the port the app will run on
EXPOSE 8080

# 7. Define the command to run the application using Gunicorn
# --workers 1: CRITICAL for a stateful bot to prevent race conditions.
# --worker-class uvicorn.workers.UvicornWorker: The magic that allows Gunicorn to run our asyncio app.
# app:app: Tells Gunicorn to run the 'app' object from the 'app.py' file.
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--worker-class", "uvicorn.workers.UvicornWorker", "app:app"]
