# GymAI Core Workflows and User Journey

This document outlines the operational flow, user journey, and how the multi-agent system interacts to provide a seamless health and fitness experience in the GymAI application. These workflows can be mapped directly into use-case diagrams or flowcharts for a presentation.

---

## 1. High-Level User Lifecycle

The user’s journey through GymAI is designed as an iterative, conversational flow guided by the AI.

1. **Onboarding (Initial State)**
   *   **Trigger:** A new user signs in and sends their first message.
   *   **Action:** The system queries the `user_state` database collection. Detecting missing required fields, it forces the conversation into the **Onboarding Flow**.
   *   **Actor:** `ProfileAgent`.
   *   **Result:** The AI converses with the user to collect weight, height, location, diet restrictions, and primary goals until all mandatory fields are stored.

2. **Plan Generation**
   *   **Trigger:** The onboarding is marked as 'complete', but the user possesses no active `weekly_plan`.
   *   **Action:** The system automatically intercepts the flow and triggers plan creation without requiring the user to explicitly ask.
   *   **Actor:** `PlannerAgent` + `CoordinatorAgent`.
   *   **Result:** A personalized 7-day workout and meal plan is generated and the user is redirected to view their calendar.

3. **Daily Execution & Active Use**
   *   **Trigger:** The user checks in, logs daily foods, inputs workout status, or asks general fitness queries.
   *   **Action:** The `CoordinatorAgent` dynamically routes the input based on prompt sentiment and intent using an LLM classifier.
   *   **Actors:** `AdjustmentAgent` (logging), `NutritionAgent` (diet questions), `CoachAgent` (motivation).

4. **Continuous Feedback Loop**
   *   **Trigger:** A daily log indicates the user failed a workout or ate over their calories, or the user actively complains about a specific exercise.
   *   **Action:** The AI evaluates constraints, creates an `adjustment` record, and updates the remaining days in the active week.
   *   **Actors:** `AdjustmentAgent` (automatic tweaks), `ModificationAgent` (user-requested changes).

---

## 2. The Agent Routing Workflow (The "Brain")

Every user message starts at the `CoordinatorAgent`. Here is the exact decision matrix executed on every request:

1. **State Check:** Read Firestore to determine if the user is fully onboarded.
   * *If NO:* Ignore conversational intent (unless it's simple motivation or a daily log) and route directly to `ProfileAgent`.
2. **Intent Detection:** Run the user's message through the lightweight `IntentClassifier` LLM to extract one of 7 distinct intents:
   *   `profile` -> Update user data.
   *   `log_activity` -> Record what the user did today.
   *   `get_plan` -> View the current daily or weekly plan.
   *   `modify_plan` -> Change the active plan (e.g., "I hate squats").
   *   `nutrition` -> General food advice.
   *   `motivation` -> Encouragement messages.
   *   `general` -> Catch-all for regular greetings.
3. **Execution & Delegation:** Based on the intent, the coordinator hands over the conversation to the most qualified sub-agent.
4. **Tool Use (MCP):** The isolated sub-agent leverages its specific set of MCP tools to query or alter the Firestore database.
5. **Response Aggregation:** The modified structured data (like updated calendar flags) and the conversational text are bundled back together by the `CoordinatorAgent` and sent to the frontend.

---

## 3. Key Micro-Workflows

### A. The "Daily Logging" Workflow
1. User types: "I finished my push workout and ate two eggs."
2. `CoordinatorAgent` detects `log_activity` intent.
3. Runs `AdjustmentAgent`.
4. Agent uses `log_daily_activity` MCP tool to save the workout and food arrays.
5. Agent detects protein/calorie discrepancy and uses `apply_adjustment` MCP tool to alter tomorrow's plan automatically (e.g., increasing calories).
6. Agent replies to the user: "Great job! I've increased your calories for tomorrow."

### B. The "Modify Plan" Workflow
1. User types: "Can we swap the squats for leg press?"
2. `CoordinatorAgent` detects `modify_plan` intent.
3. Checks if a plan exists. (If not, generates one). 
4. Runs `ModificationAgent`.
5. Agent uses `modify_plan_days` MCP tool to rewrite the specific day's JSON structure in the `weekly_plans` collection.
6. Returns UI flags to notify the frontend to re-render the calendar component.

---

## PPT Slide Suggestions
* **Slide 1: The User Journey** (A visual timeline: Onboarding -> Plan Generation -> Daily Logging -> Continuous AI Adjustment).
* **Slide 2: Request Routing Matrix** (A flowchart showing the Coordinator Agent intercepting a message and routing it to the 6 sub-agents).
* **Slide 3: Automatic Adjustments** (Highlighting the "Daily Logging" workflow, where an action automatically triggers the Adjustment Agent to rewrite tomorrow's goals).
