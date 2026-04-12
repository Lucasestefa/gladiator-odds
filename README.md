# ⚔️ Gladiator Odds Platform

Multi-platform betting intelligence system con análisis de value bets, 
arbitrajes y predicciones IA. Compatible con Bet365, Betway, Betfair, 
Codere, Pinnacle y más.

---

## 🏗️ Arquitectura

```
gladiator-odds/
├── backend/                  # FastAPI + Python
│   └── app/
│       ├── main.py           # Entry point
│       ├── core/
│       │   ├── config.py     # Variables de entorno
│       │   └── database.py   # Conexión PostgreSQL
│       ├── models/
│       │   └── models.py     # Users, Signals, Bets, Platforms
│       ├── api/
│       │   ├── auth.py       # Login, registro, JWT
│       │   ├── users.py      # Gestión de usuarios
│       │   ├── signals.py    # Señales en tiempo real
│       │   ├── platforms.py  # Gestión de plataformas
│       │   ├── betting.py    # Historial y auto-ejecución
│       │   └── webhooks.py   # Stripe + MercadoPago
│       └── services/
│           ├── signals_service.py   # The Odds API + value/arb engine
│           ├── betfair_service.py   # Auto-ejecución Betfair
│           └── whatsapp_service.py  # Notificaciones GL2
├── frontend/                 # Next.js
│   └── src/
│       ├── app/              # App Router
│       ├── components/       # UI components
│       └── lib/              # API client, auth
├── infrastructure/
│   └── docker-compose.yml    # Full stack local
└── .env.example              # Variables de entorno
```

---

## 🚀 Setup rápido (desarrollo)

### 1. Clonar y configurar entorno

```bash
git clone https://github.com/gladiator/odds-platform.git
cd gladiator-odds
cp .env.example .env
# Completar .env con tus API keys
```

### 2. Levantar con Docker (recomendado)

```bash
cd infrastructure
docker-compose up -d
```

Servicios disponibles:
- Backend API: http://localhost:8000
- Frontend: http://localhost:3000
- n8n (GL3): http://localhost:5678
- API Docs: http://localhost:8000/docs

### 3. Setup manual (sin Docker)

```bash
# Backend
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# Frontend (en otra terminal)
cd frontend
npm install
npm run dev
```

---

## 🔑 APIs necesarias

| API | Para qué | Costo | Link |
|-----|----------|-------|------|
| **The Odds API** | Odds de 40+ bookmakers | Gratis 500req/mes | the-odds-api.com |
| **Betfair** | Auto-ejecución | % comisión | developer.betfair.com |
| **Twilio** | WhatsApp (GL2) | ~$0.005/msg | twilio.com |
| **Stripe** | Pagos globales | 2.9% + $0.30 | stripe.com |
| **MercadoPago** | Pagos Argentina | 3.99% | mercadopago.com.ar |
| **Anthropic** | Análisis IA | Pay per use | console.anthropic.com |

---

## 📋 Planes y precios

| Plan | Precio | Incluye |
|------|--------|---------|
| Señales WA | $9/mes | Solo alertas WhatsApp |
| Starter | $15/mes | Dashboard + 3 señales/día |
| Pro | $39/mes | Ilimitado + arbitrajes |
| Elite | $89/mes | Auto-ejecución Betfair + soporte |

---

## 🎯 Modo Hood

Hood (COO de Gladiator) puede activar el modo de operación maestra:
- Gestión automática de señales y distribución
- Reportes diarios automáticos a usuarios
- Auto-cobro de suscripciones vía n8n (GL3)
- Optimización de estrategias según performance
- Captación de usuarios vía bots RRSS

Activar en: Dashboard → Modo Hood → Toggle ON

---

## 🔗 Integración con Gladiator Holdings

| Empresa | Rol en este proyecto |
|---------|---------------------|
| **GL1 — Veloce Studio** | Contenido y marketing para adquirir usuarios |
| **GL2 — Gladiator Bot Solutions** | WhatsApp bot para distribución de señales |
| **GL3 — Gladiator Automate** | n8n: automatización de cobros y onboarding |

---

## ⚖️ Legal

El análisis de odds y value betting es legal en la mayoría de jurisdicciones.
La ejecución automática requiere verificar términos y condiciones de cada plataforma.
Betfair Exchange permite bots explícitamente.
Jugar con responsabilidad. +18.
