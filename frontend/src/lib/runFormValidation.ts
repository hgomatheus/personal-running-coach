/**
 * Manual run entry form validation logic.
 *
 * Extracted from the run entry page component so it can be unit-tested
 * independently of the Svelte runtime.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface RunFormFields {
	date: string;
	distanceKm: string;
	duration: string;
	avgHeartRate: string;
	notes: string;
}

export type ValidationErrors = Record<string, string>;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Parse a duration string in mm:ss or hh:mm:ss format.
 * Returns total seconds, or null if the format is invalid.
 */
export function parseDuration(value: string): number | null {
	const trimmed = value.trim();
	// hh:mm:ss
	const hmsMatch = trimmed.match(/^(\d+):([0-5]\d):([0-5]\d)$/);
	if (hmsMatch) {
		const h = parseInt(hmsMatch[1], 10);
		const m = parseInt(hmsMatch[2], 10);
		const s = parseInt(hmsMatch[3], 10);
		return h * 3600 + m * 60 + s;
	}
	// mm:ss
	const msMatch = trimmed.match(/^(\d+):([0-5]\d)$/);
	if (msMatch) {
		const m = parseInt(msMatch[1], 10);
		const s = parseInt(msMatch[2], 10);
		return m * 60 + s;
	}
	return null;
}

/** Returns true when the validation errors object contains no entries. */
export function isValid(errors: ValidationErrors): boolean {
	return Object.keys(errors).length === 0;
}

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

/**
 * Validates the manual run entry form fields.
 *
 * Returns an object whose keys are field names and values are error messages.
 * An empty object means the form is valid.
 */
export function validateRunForm(fields: RunFormFields): ValidationErrors {
	const errs: ValidationErrors = {};

	// Date — required
	if (!fields.date) {
		errs.date = 'Date is required.';
	}

	// Distance — required, > 0
	const km = parseFloat(fields.distanceKm);
	if (!fields.distanceKm.trim()) {
		errs.distanceKm = 'Distance is required.';
	} else if (isNaN(km) || km <= 0) {
		errs.distanceKm = 'Distance must be greater than 0.';
	}

	// Duration — required, valid format, > 0
	if (!fields.duration.trim()) {
		errs.duration = 'Duration is required.';
	} else {
		const secs = parseDuration(fields.duration);
		if (secs === null) {
			errs.duration = 'Enter duration as mm:ss or hh:mm:ss (e.g. 45:30 or 1:05:00).';
		} else if (secs <= 0) {
			errs.duration = 'Duration must be greater than 0.';
		}
	}

	// Heart rate — optional, but if provided must be 30–250
	if (fields.avgHeartRate.trim() !== '') {
		const hr = parseInt(fields.avgHeartRate, 10);
		if (isNaN(hr) || !Number.isInteger(hr)) {
			errs.avgHeartRate = 'Heart rate must be a whole number.';
		} else if (hr < 30 || hr > 250) {
			errs.avgHeartRate = 'Heart rate must be between 30 and 250 bpm.';
		}
	}

	// Notes — always optional, no validation needed

	return errs;
}
