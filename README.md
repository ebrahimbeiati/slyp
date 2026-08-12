# Slyp ── The Financial MOT For Young Adults

Slyp turns confusing monthly payslips into an actionable, live financial dashboard. Built during the Hackathon.

## 🚀 Live Demo & Links

- **Live Application**: [Insert Vercel Link Here]
- **Figma Design File**: [Insert Yanxi's Figma View Link Here]
- **Pitch Deck Presentations**: Located in `/docs/`

## 🛠️ The Tech Stack

- **Frontend**: Next.js (React), Tailwind CSS, Shadcn/ui
- **Backend & AI Engine**: Node.js/Python, Google Gemini 2.5 Flash / Claude 3.5 Sonnet
- **Deployment**: Vercel

## 🛡️ Privacy Guard Architecture

Slyp operates as a stateless processor. Uploaded documents are parsed entirely in memory via secure LLM vision APIs, stripped of Personal Identifiable Information (PII) like names, address blocks, and national insurance numbers, and are completely discarded within seconds. No user payroll data ever touches a persistent database.
