# Use 'slim' to avoid dependency installation headaches
FROM python:3.12-slim

# Set the working directory
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install dependencies without caching to save space
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the code
COPY . .

# Cloud Run expects the app to listen on port 8080
# This command explicitly binds it to 0.0.0.0 so the world can access it
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]