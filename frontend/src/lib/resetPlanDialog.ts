/**
 * Reset Plan confirmation dialog state machine.
 *
 * Extracted from the plan page component so it can be unit-tested
 * independently of the Svelte runtime.
 *
 * The state machine tracks three pieces of state:
 *   - `isOpen`:    whether the confirmation dialog is visible
 *   - `isLoading`: whether the DELETE API call is in progress
 *   - `error`:     any error message returned by the API call
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ResetPlanDialogState {
	isOpen: boolean;
	isLoading: boolean;
	error: string | null;
}

/**
 * A function that deletes a training plan.
 * Matches the signature of `plansApi.delete(planId, profileId)`.
 */
export type DeletePlanFn = (planId: number, profileId: number) => Promise<void>;

/**
 * A function that performs a redirect after a successful reset.
 * Defaults to `window.location.href = '/onboarding'` in the real app.
 */
export type RedirectFn = (url: string) => void;

// ---------------------------------------------------------------------------
// Initial state
// ---------------------------------------------------------------------------

/** Returns the initial (closed, idle) dialog state. */
export function createInitialState(): ResetPlanDialogState {
	return {
		isOpen: false,
		isLoading: false,
		error: null
	};
}

// ---------------------------------------------------------------------------
// State transitions
// ---------------------------------------------------------------------------

/**
 * Opens the confirmation dialog and clears any previous error.
 * Returns the new state (does not mutate the input).
 */
export function openDialog(state: ResetPlanDialogState): ResetPlanDialogState {
	return { ...state, isOpen: true, error: null };
}

/**
 * Closes the dialog and clears any error.
 * Has no effect while a reset is in progress (`isLoading === true`).
 * Returns the new state (does not mutate the input).
 */
export function closeDialog(state: ResetPlanDialogState): ResetPlanDialogState {
	if (state.isLoading) return state;
	return { ...state, isOpen: false, error: null };
}

// ---------------------------------------------------------------------------
// Async action
// ---------------------------------------------------------------------------

/**
 * Executes the plan reset:
 *   1. Sets `isLoading = true`.
 *   2. Calls `deleteFn(planId, profileId)`.
 *   3a. On success: closes the dialog and calls `redirectFn('/onboarding')`.
 *   3b. On failure: sets `error` to the error message and keeps the dialog open.
 *
 * The `onStateChange` callback is invoked every time the state changes so
 * callers can react to intermediate states (e.g. show a spinner).
 *
 * Returns the final state after the operation completes.
 */
export async function confirmReset(
	state: ResetPlanDialogState,
	planId: number,
	profileId: number,
	deleteFn: DeletePlanFn,
	redirectFn: RedirectFn,
	onStateChange: (s: ResetPlanDialogState) => void
): Promise<ResetPlanDialogState> {
	// Transition to loading
	let current: ResetPlanDialogState = { ...state, isLoading: true, error: null };
	onStateChange(current);

	try {
		await deleteFn(planId, profileId);
		// Success: close dialog then redirect
		current = { ...current, isLoading: false, isOpen: false };
		onStateChange(current);
		redirectFn('/onboarding');
	} catch (e) {
		// Failure: surface error, keep dialog open
		const message =
			e instanceof Error ? e.message : 'Failed to reset plan. Please try again.';
		current = { ...current, isLoading: false, error: message };
		onStateChange(current);
	}

	return current;
}
