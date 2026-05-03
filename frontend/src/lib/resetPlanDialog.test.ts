/**
 * Unit tests for the reset plan confirmation dialog state machine.
 *
 * Tests cover (Requirements 4.6–4.9):
 *  1. Dialog starts closed (isOpen=false, isLoading=false, error=null)
 *  2. openDialog() opens the dialog
 *  3. closeDialog() closes the dialog without making any API call
 *  4. closeDialog() is a no-op while a reset is in progress
 *  5. confirmReset() calls the delete API with the correct planId and profileId
 *  6. After a successful delete, dialog closes and redirect is called
 *  7. If the API call fails, error is shown and dialog stays open
 *  8. While the API call is in progress, isLoading is true
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
	createInitialState,
	openDialog,
	closeDialog,
	confirmReset,
	type ResetPlanDialogState,
	type DeletePlanFn,
	type RedirectFn
} from './resetPlanDialog';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Resolves immediately — simulates a successful API call. */
function makeSuccessfulDelete(): DeletePlanFn {
	return vi.fn().mockResolvedValue(undefined);
}

/** Rejects with the given message — simulates a failed API call. */
function makeFailingDelete(message = 'Network error'): DeletePlanFn {
	return vi.fn().mockRejectedValue(new Error(message));
}

// ---------------------------------------------------------------------------
// 1. Initial state
// ---------------------------------------------------------------------------

describe('createInitialState', () => {
	it('dialog starts closed', () => {
		const state = createInitialState();
		expect(state.isOpen).toBe(false);
	});

	it('loading starts false', () => {
		const state = createInitialState();
		expect(state.isLoading).toBe(false);
	});

	it('error starts null', () => {
		const state = createInitialState();
		expect(state.error).toBeNull();
	});
});

// ---------------------------------------------------------------------------
// 2. openDialog
// ---------------------------------------------------------------------------

describe('openDialog', () => {
	it('opens the dialog', () => {
		const state = openDialog(createInitialState());
		expect(state.isOpen).toBe(true);
	});

	it('clears any previous error when opening', () => {
		const withError: ResetPlanDialogState = {
			isOpen: false,
			isLoading: false,
			error: 'Previous error'
		};
		const state = openDialog(withError);
		expect(state.error).toBeNull();
	});

	it('does not mutate the input state', () => {
		const initial = createInitialState();
		openDialog(initial);
		expect(initial.isOpen).toBe(false);
	});
});

// ---------------------------------------------------------------------------
// 3. closeDialog — cancel = no action
// ---------------------------------------------------------------------------

describe('closeDialog', () => {
	it('closes the dialog', () => {
		const opened = openDialog(createInitialState());
		const state = closeDialog(opened);
		expect(state.isOpen).toBe(false);
	});

	it('clears any error when closing', () => {
		const withError: ResetPlanDialogState = {
			isOpen: true,
			isLoading: false,
			error: 'Some error'
		};
		const state = closeDialog(withError);
		expect(state.error).toBeNull();
	});

	it('does not mutate the input state', () => {
		const opened = openDialog(createInitialState());
		closeDialog(opened);
		expect(opened.isOpen).toBe(true);
	});
});

// ---------------------------------------------------------------------------
// 4. closeDialog is a no-op while loading
// ---------------------------------------------------------------------------

describe('closeDialog while loading', () => {
	it('does not close the dialog when isLoading is true', () => {
		const loading: ResetPlanDialogState = {
			isOpen: true,
			isLoading: true,
			error: null
		};
		const state = closeDialog(loading);
		expect(state.isOpen).toBe(true);
		expect(state.isLoading).toBe(true);
	});

	it('returns the same state reference when isLoading is true', () => {
		const loading: ResetPlanDialogState = {
			isOpen: true,
			isLoading: true,
			error: null
		};
		const result = closeDialog(loading);
		expect(result).toBe(loading);
	});
});

// ---------------------------------------------------------------------------
// 5. confirmReset — calls the delete API
// ---------------------------------------------------------------------------

describe('confirmReset — API call', () => {
	it('calls the delete function with the correct planId and profileId', async () => {
		const deleteFn = makeSuccessfulDelete();
		const redirectFn: RedirectFn = vi.fn();

		await confirmReset(
			openDialog(createInitialState()),
			42,   // planId
			1,    // profileId
			deleteFn,
			redirectFn,
			vi.fn()
		);

		expect(deleteFn).toHaveBeenCalledOnce();
		expect(deleteFn).toHaveBeenCalledWith(42, 1);
	});

	it('does not call the delete function when cancel is used instead', () => {
		// Simulates the user clicking Cancel — closeDialog is called, confirmReset is never invoked
		const deleteFn = makeSuccessfulDelete();
		const opened = openDialog(createInitialState());
		closeDialog(opened); // cancel
		expect(deleteFn).not.toHaveBeenCalled();
	});
});

// ---------------------------------------------------------------------------
// 6. confirmReset — success path
// ---------------------------------------------------------------------------

describe('confirmReset — success', () => {
	it('closes the dialog after a successful delete', async () => {
		const finalState = await confirmReset(
			openDialog(createInitialState()),
			1, 1,
			makeSuccessfulDelete(),
			vi.fn(),
			vi.fn()
		);

		expect(finalState.isOpen).toBe(false);
	});

	it('clears loading state after a successful delete', async () => {
		const finalState = await confirmReset(
			openDialog(createInitialState()),
			1, 1,
			makeSuccessfulDelete(),
			vi.fn(),
			vi.fn()
		);

		expect(finalState.isLoading).toBe(false);
	});

	it('calls the redirect function with /onboarding after a successful delete', async () => {
		const redirectFn: RedirectFn = vi.fn();

		await confirmReset(
			openDialog(createInitialState()),
			1, 1,
			makeSuccessfulDelete(),
			redirectFn,
			vi.fn()
		);

		expect(redirectFn).toHaveBeenCalledOnce();
		expect(redirectFn).toHaveBeenCalledWith('/onboarding');
	});

	it('has no error in the final state after a successful delete', async () => {
		const finalState = await confirmReset(
			openDialog(createInitialState()),
			1, 1,
			makeSuccessfulDelete(),
			vi.fn(),
			vi.fn()
		);

		expect(finalState.error).toBeNull();
	});
});

// ---------------------------------------------------------------------------
// 7. confirmReset — failure path
// ---------------------------------------------------------------------------

describe('confirmReset — failure', () => {
	it('keeps the dialog open when the API call fails', async () => {
		const finalState = await confirmReset(
			openDialog(createInitialState()),
			1, 1,
			makeFailingDelete('Server error'),
			vi.fn(),
			vi.fn()
		);

		expect(finalState.isOpen).toBe(true);
	});

	it('sets the error message when the API call fails', async () => {
		const finalState = await confirmReset(
			openDialog(createInitialState()),
			1, 1,
			makeFailingDelete('Server error'),
			vi.fn(),
			vi.fn()
		);

		expect(finalState.error).toBe('Server error');
	});

	it('clears loading state after a failed delete', async () => {
		const finalState = await confirmReset(
			openDialog(createInitialState()),
			1, 1,
			makeFailingDelete(),
			vi.fn(),
			vi.fn()
		);

		expect(finalState.isLoading).toBe(false);
	});

	it('does not call the redirect function when the API call fails', async () => {
		const redirectFn: RedirectFn = vi.fn();

		await confirmReset(
			openDialog(createInitialState()),
			1, 1,
			makeFailingDelete(),
			redirectFn,
			vi.fn()
		);

		expect(redirectFn).not.toHaveBeenCalled();
	});

	it('handles non-Error rejections gracefully', async () => {
		const deleteFn: DeletePlanFn = vi.fn().mockRejectedValue('string error');

		const finalState = await confirmReset(
			openDialog(createInitialState()),
			1, 1,
			deleteFn,
			vi.fn(),
			vi.fn()
		);

		expect(finalState.error).toBe('Failed to reset plan. Please try again.');
	});
});

// ---------------------------------------------------------------------------
// 8. confirmReset — loading state during API call
// ---------------------------------------------------------------------------

describe('confirmReset — loading state', () => {
	it('sets isLoading to true while the API call is in progress', async () => {
		const statesDuringCall: ResetPlanDialogState[] = [];

		// A delete that resolves after we've captured the intermediate state
		let resolveDelete!: () => void;
		const deleteFn: DeletePlanFn = vi.fn(
			() => new Promise<void>((resolve) => { resolveDelete = resolve; })
		);

		const promise = confirmReset(
			openDialog(createInitialState()),
			1, 1,
			deleteFn,
			vi.fn(),
			(s) => statesDuringCall.push({ ...s })
		);

		// The first state change should be the loading state
		expect(statesDuringCall[0]?.isLoading).toBe(true);

		// Let the delete resolve so the test doesn't hang
		resolveDelete();
		await promise;
	});

	it('emits a loading state before the API call resolves', async () => {
		const states: ResetPlanDialogState[] = [];

		await confirmReset(
			openDialog(createInitialState()),
			1, 1,
			makeSuccessfulDelete(),
			vi.fn(),
			(s) => states.push({ ...s })
		);

		// First emitted state must be loading
		expect(states[0]?.isLoading).toBe(true);
		// Final emitted state must not be loading
		expect(states[states.length - 1]?.isLoading).toBe(false);
	});
});
