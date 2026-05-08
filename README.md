
# IMC Prosperity 4 — Rocky Mountain Goats
---
This writeup shares our strategies for the algorithmic and manual challenges of IMC Prosperity 4 (2026), which brought us to a global rank of 154th out of 22000+ teams. This was the first attempt at a quantitative trading competition for all of us, and we formed a team through the Discord server created by IMC for this competition. 

> Team Members: Alex Zhang, Annanye Naik, Saksham Arora, Zain Hirji

---

# TL;DR

A short summary of the competition from your perspective.

Example:

> We focused primarily on robust market making and simple statistical arbitrage rather than highly complex predictive models. Our strongest rounds came from identifying structural inefficiencies in basket pricing and inventory management, while our weakest performance came from overfitting short-term signals in later rounds.

Main takeaways:
- What worked
- What failed
- Biggest lesson
- Most profitable strategy
- Most painful bug

---

# Competition Overview

Briefly explain the structure of Prosperity 4.

Example points:
- 5 rounds
- Algorithmic + manual challenges
- Increasing market complexity each round
- Limited observability / adversarial environment
- Importance of iteration speed

---

# Team Workflow

## Research Process

Describe:
- how ideas were generated
- how signals were tested
- how decisions were made

Example:
- notebooks for exploration
- replay system for backtesting
- parameter sweeps
- visualization tooling

---

## Infrastructure

Describe your setup.

### Tech Stack
- Python
- pandas / numpy
- plotting libraries
- local simulator

### Bot Architecture

```text
Trader.run(state)
    ├── Market Making
    ├── Signal Generation
    ├── Inventory Management
    ├── Basket Arbitrage
    └── Risk Controls
