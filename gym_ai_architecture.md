# GymAI Application Architecture Overview

This document provides a detailed breakdown of the technical components used in the GymAI application. It is structured to help you easily extract the information for a PowerPoint (PPT) presentation.

---

## 1. Multi-Agent System (ADK Agents)

GymAI utilizes a sophisticated multi-agent architecture built on the Google ADK (Agent Development Kit). At the core, it employs a router pattern where a primary coordinator assigns tasks to specialized sub-agents based on the user's intent.

### **CoordinatorAgent**
- **Role:** The primary entry point for all chat requests.
- **Function:** Uses a lightweight LLM Agent to perform intent classification (e.g., detecting if the user wants to log activity, modify a plan, or needs motivation).
- **Workflow:** Routes the request to the correct sub-agent. For example, if a user's profile is incomplete, it routes to the ProfileAgent first. It also automatically triggers plan generation or adjustments based on the conversation context.

### **Sub-Agents**
- **ProfileAgent:** Handles user onboarding, gathering necessary fitness data such as weight, height, location, diet preferences, and goals.
- **PlannerAgent:** Responsible for generating personalized 7-day workout and nutrition plans based on the user's profile and constraints.
- **ModificationAgent:** Triggers when a user requests a change to their existing plan (e.g., swapping out an exercise or a meal they dislike). 
- **AdjustmentAgent:** Analyzes daily logs and workout completions, automatically adjusting tomorrow's plan intensity or calorie targets based on today's performance.
- **NutritionAgent:** Specialized in answering general questions about food, macros, meals, or diet advice.
- **CoachAgent:** Acts as a motivational figure, responding to user sentiment, providing encouragement, and summarizing progress.

---

## 2. Database (Google Cloud Firestore)

The application utilizes **Google Cloud Firestore** as its primary, NoSQL database. It replaces an older SQLite implementation with a fully asynchronous layer while maintaining the same structural shapes for seamless tool integration.

### **Core Collections:**
- `users`: Stores user profile data (weight, height, diet type, goals). The document ID is the user's ID.
- `auth`: Stores authentication credentials (email, hashed passwords).
- `user_state`: Tracks the user's onboarding progression, determining which profile fields are still missing.
- `weekly_plans`: Stores the generated 7-day fitness and meal plans. It is linked to a user ID and a week start date.
- `daily_logs`: Records per-day activity logs, including whether workouts were completed and actual food consumed. (Document ID format: `{user_id}_{log_date}`).
- `adjustments`: Stores AI-generated plan tweaks indicating why, when, and how a user's plan was modified.
- `chat_history`: Keeps a sequential log of the conversation turns between the user and the system.
- `weight_history`: Maintains periodic snapshots of the user's weight to calculate progress over time.

---

## 3. MCP Tools (Model Context Protocol)

The system exposes specific, deterministic tools to the Claude/Gemini LLM agents. These tools allow the AI to directly interact with the Firestore database and manage the user's physical data.

### **Profile & State Tools**
- `save_user_profile`: Saves or updates specific fields in the user's profile. Records a weight snapshot if weight is updated.
- `get_user_profile`: Retrieves the user's current profile and a list of any missing onboarding fields.
- `get_progress_summary`: Returns a calculated consistency score, net weight change, and total completed days.

### **Planning Tools**
- `generate_weekly_plan`: Signals the backend to run the PlannerAgent to forge a new 7-day regimen.
- `get_weekly_plan`: Fetches the user's current active 7-day plan.
- `get_daily_plan`: Extracts the detailed workout and meals assigned for one specific day.
- `modify_plan_days`: Applies selective updates to specific days of a weekly plan (e.g., changing "Push" workout to "Yoga", or altering a meal).

### **Logging & Adjustment Tools**
- `log_daily_activity`: Allows the AI to record the user's daily workout status and ingested calories/foods based on chat input.
- `update_day_status`: Sets a specific day's status to 'pending', 'completed', 'missed', or 'adjusted'.
- `apply_adjustment`: Stores an AI-generated adjustment (e.g., increasing workout intensity or changing caloric targets) based on recent user performance.

---

## PPT Slide Suggestions

*   **Slide 1: Architecture Overview** (Diagram showing the Coordinator Agent routing to the 6 Sub-Agents).
*   **Slide 2: The Agent Ecosystem** (List the Agents and their specific roles).
*   **Slide 3: Data Foundation** (Highlight Google Cloud Firestore and the 8 key collections mapping the user's journey).
*   **Slide 4: AI Tools (MCP)** (Explain how the LLMs use MCP tools to read/write deterministic data like logging daily activity or fetching physical progress).
