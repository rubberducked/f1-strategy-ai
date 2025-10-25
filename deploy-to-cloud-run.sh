#!/bin/bash

# deploy-to-cloud-run.sh
# Comprehensive deployment script for F1 Strategy AI to Google Cloud Run
# Description: Automates deployment of backend and frontend services to Google Cloud Run

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info(){ echo -e "${BLUE}[INFO]${NC} $*"; }
success(){ echo -e "${GREEN}[SUCCESS]${NC} $*"; }
warn(){ echo -e "${YELLOW}[WARNING]${NC} $*"; }
err(){ echo -e "${RED}[ERROR]${NC} $*"; }

print_banner(){
  echo -e "${BLUE}\n==================================================";
  echo "   F1 Strategy AI - Cloud Run Deployment";
  echo -e "==================================================${NC}";
}

check_prereqs(){
  info "Checking prerequisites..."
  command -v gcloud >/dev/null || { err "gcloud not installed"; echo "https://cloud.google.com/sdk/docs/install"; exit 1; }
  command -v docker >/dev/null || { err "Docker not installed"; echo "https://docs.docker.com/get-docker/"; exit 1; }
  gcloud auth list --filter=status:ACTIVE --format='value(account)' | grep -q . || { warn "No active gcloud account"; gcloud auth login; }
  PROJECT_ID=$(gcloud config get-value project 2>/dev/null || true)
  if [[ -z "${PROJECT_ID}" || "${PROJECT_ID}" == "(unset)" ]]; then
    read -r -p "Enter GCP Project ID: " PROJECT_ID
    gcloud config set project "$PROJECT_ID"
  fi
  gcloud projects describe "$PROJECT_ID" >/dev/null || { err "Project $PROJECT_ID not accessible"; exit 1; }
  success "Using project: $PROJECT_ID"
}

enable_apis(){
  info "Enabling required APIs..."
  local apis=(run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com cloudresourcemanager.googleapis.com iam.googleapis.com)
  for a in "${apis[@]}"; do
    info "Enabling $a"
    gcloud services enable "$a" --project "$PROJECT_ID" || warn "$a may already be enabled"
  done
  success "APIs enabled"
}

set_config(){
  REGION=${REGION:-us-central1}
  read -r -p "Region [$REGION]: " r; [[ -n "$r" ]] && REGION="$r"
  BACKEND_SERVICE=f1-strategy-backend
  FRONTEND_SERVICE=f1-strategy-frontend
  BACKEND_IMAGE=gcr.io/$PROJECT_ID/$BACKEND_SERVICE
  FRONTEND_IMAGE=gcr.io/$PROJECT_ID/$FRONTEND_SERVICE
  success "Config -> Region: $REGION, Backend: $BACKEND_SERVICE, Frontend: $FRONTEND_SERVICE"
}

deploy_backend(){
  info "Deploying backend..."
  [[ -d backend ]] || { err "backend directory missing"; exit 1; }
  pushd backend >/dev/null
  if [[ ! -f Dockerfile ]]; then
    warn "No backend Dockerfile, creating a minimal one"
    cat > Dockerfile <<'EOF'
FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt || true
COPY . .
ENV PORT=8080
EXPOSE 8080
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 app:app
EOF
  fi
  info "Building backend image"
  gcloud builds submit --tag "$BACKEND_IMAGE" --project "$PROJECT_ID"
  info "Deploying backend to Cloud Run"
  gcloud run deploy "$BACKEND_SERVICE" \
    --image "$BACKEND_IMAGE" --platform managed --region "$REGION" \
    --allow-unauthenticated --memory 512Mi --cpu 1 --max-instances 10 \
    --project "$PROJECT_ID"
  BACKEND_URL=$(gcloud run services describe "$BACKEND_SERVICE" --platform managed --region "$REGION" --format 'value(status.url)' --project "$PROJECT_ID")
  popd >/dev/null
  success "Backend URL: $BACKEND_URL"
}

deploy_frontend(){
  info "Deploying frontend..."
  [[ -d frontend ]] || { err "frontend directory missing"; exit 1; }
  pushd frontend >/dev/null
  if [[ ! -f Dockerfile ]]; then
    warn "No frontend Dockerfile, creating a minimal one"
    cat > Dockerfile <<'EOF'
FROM node:18-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build || true
ENV PORT=8080
EXPOSE 8080
CMD ["npm","start"]
EOF
  fi
  if [[ -n "${BACKEND_URL:-}" ]]; then
    echo "REACT_APP_BACKEND_URL=$BACKEND_URL" > .env.production
    info "Set REACT_APP_BACKEND_URL=$BACKEND_URL"
  fi
  info "Building frontend image"
  gcloud builds submit --tag "$FRONTEND_IMAGE" --project "$PROJECT_ID"
  info "Deploying frontend to Cloud Run"
  gcloud run deploy "$FRONTEND_SERVICE" \
    --image "$FRONTEND_IMAGE" --platform managed --region "$REGION" \
    --allow-unauthenticated --memory 512Mi --cpu 1 --max-instances 10 \
    --project "$PROJECT_ID"
  FRONTEND_URL=$(gcloud run services describe "$FRONTEND_SERVICE" --platform managed --region "$REGION" --format 'value(status.url)' --project "$PROJECT_ID")
  popd >/dev/null
  success "Frontend URL: $FRONTEND_URL"
}

test_endpoints(){
  info "Testing endpoints..."
  if [[ -n "${BACKEND_URL:-}" ]]; then
    curl -sf "$BACKEND_URL/health" >/dev/null 2>&1 && success "Backend /health OK" || \
    { curl -sf "$BACKEND_URL/" >/dev/null 2>&1 && success "Backend root OK" || warn "Backend test failed"; }
  fi
  if [[ -n "${FRONTEND_URL:-}" ]]; then
    curl -sf "$FRONTEND_URL/" >/dev/null 2>&1 && success "Frontend OK" || warn "Frontend test failed"
  fi
}

summary(){
  echo -e "${GREEN}\n================ Deployment Complete ================${NC}"
  echo "Backend:  ${BACKEND_URL:-n/a}"; echo "Frontend: ${FRONTEND_URL:-n/a}"
  echo "Logs:"; echo "  gcloud run services logs read $BACKEND_SERVICE --region $REGION"
  echo "  gcloud run services logs read $FRONTEND_SERVICE --region $REGION"
}

main(){
  print_banner; check_prereqs; set_config; enable_apis
  echo "What to deploy?"; echo "  1) Both"; echo "  2) Backend only"; echo "  3) Frontend only"
  read -r -p "Choice [1-3]: " c
  case "$c" in
    1) deploy_backend; deploy_frontend;;
    2) deploy_backend;;
    3) deploy_frontend;;
    *) err "Invalid choice"; exit 1;;
  esac
  test_endpoints; summary
}

main "$@"
