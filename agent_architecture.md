# FitnessAI Agent Architecture & Workflows

This document outlines the multi-agent architecture of the FitnessAI application, detailing the purpose of each AI agent and exactly when and how they are invoked.

## Overview

FitnessAI uses a multi-agent system where different specialized agents handle specific aspects of the user's fitness journey. The application is built on FastAPI (`backend/main.py`), which exposes REST API endpoints. Most chat interactions are routed through a central **Coordinator Agent**, while other endpoints directly invoke specific agents.

---

## 1. Coordinator Agent (`coordinator.py`)
**Purpose:** Acts as the primary router and orchestrator for the conversational interface. 
**When it is called:** 
- It is instantiated in `main.py` and invoked every time a user sends a message to the `POST /chat` endpoint.

**How it works:**
1. **Onboarding Check:** It checks if the user has completed their profile setup. If not, it intercepts the message and routes it to the **Profile Agent** (unless the user is explicitly trying to log activity or asking for motivation).
2. **Intent Detection:** It uses a lightweight LLM prompt to classify the user's message into one of several predefined intents: `profile`, `log_activity`, `get_plan`, `nutrition`, `motivation`, or `general`.
3. **Routing:** Based on the detected intent, it delegates the query to the corresponding specialized sub-agent.
4. **Auto-Triggering:** If routing to the Profile Agent results in the onboarding being completed, the Coordinator automatically triggers the **Planner Agent** to generate the user's first 7-day fitness plan.

---

## 2. Profile Agent (`profile_agent.py`)
**Purpose:** Collects, manages, and updates user profile data (weight, goals, diet preferences, available time, location).
**When it is called:**
- **During Chat:** Routed by the Coordinator when the detected intent is `profile`.
- **Forced Onboarding:** Forced by the Coordinator for any chat message if the user's profile is incomplete (ensuring the user cannot bypass onboarding).

---

## 3. Planner Agent (`planner_agent.py`)
**Purpose:** Generates and answers questions about the user's 7-day fitness and meal plan based on their profile.
**When it is called:**
- **During Chat:** Routed by the Coordinator if the intent is `get_plan`. It will either generate a new plan if one doesn't exist, or discuss the existing plan with the user.
- **Auto-Generation:** Automatically called by the Coordinator immediately after the **Profile Agent** successfully finishes onboarding a user.
- **Direct API Call:** Called directly by the `POST /generate-plan` endpoint in `main.py` to forcefully regenerate a weekly plan outside of the chat flow.

---

## 4. Adjustment Agent (`adjustment_agent.py`)
**Purpose:** Evaluates daily logs (workouts done/skipped, food intake) and makes dynamic adjustments to the user's overall plan based on their adherence and progress.
**When it is called:**
- **During Chat:** Routed by the Coordinator when the intent is `log_activity`.
- **Direct API Call:** Called directly by the `POST /log` endpoint in `main.py`. When a user logs an activity via the UI (non-chat), the backend saves the log and automatically passes a summary of the logged data to the Adjustment Agent to evaluate and provide feedback/adjustments.

---

## 5. Nutrition Agent (`nutrition_agent.py`)
**Purpose:** Handles tailored questions specifically about food, meals, diets, and calorie tracking.
**When it is called:**
- **During Chat:** Routed by the Coordinator when the detected intent is `nutrition`.

---

## 6. Coach Agent (`coach_agent.py`)
**Purpose:** Acts as a motivational coach, analyzing progress and providing encouragement or support.
**When it is called:**
- **During Chat:** Routed by the Coordinator when the user's detected intent is `motivation` (e.g., they need encouragement or ask about their progress).
- **Direct API Call:** Called directly by the `GET /progress` endpoint in `main.py`. When the dashboard fetches user stats (consistency, weight change), it also triggers the Coach Agent to generate a brief, personalized motivational message for the frontend's dashboard.

---

## 7. General Chat (Fallback)
**Purpose:** Handles greetings or out-of-scope conversational topics.
**When it is called:**
- **During Chat:** Handled directly by a fallback LLM prompt within the **Coordinator Agent** when the detected intent is `general` or unrecognized.
