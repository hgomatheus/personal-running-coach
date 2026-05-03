/**
 * Onboarding form validation logic.
 *
 * Extracted from the onboarding page component so it can be unit-tested
 * independently of the Svelte runtime.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Step1Fields {
	profileName: string;
	dateOfBirth: string;
	biologicalSex: string;
}

export interface Step2Fields {
	raceDistancePreset: number | 'custom';
	raceDistanceCustomKm: string;
	raceDate: string;
}

export interface Step3Fields {
	currentWeeklyKm: string;
	longestRecentRunKm: string;
	/** True when a Strava bulk import has been successfully uploaded. */
	bulkImportSuccess: boolean;
}

export type ValidationErrors = Record<string, string>;

// ---------------------------------------------------------------------------
// Step 1 — Profile Setup
// ---------------------------------------------------------------------------

/**
 * Validates Step 1 (profile name, date of birth, biological sex).
 *
 * Returns an object whose keys are field names and values are error messages.
 * An empty object means the step is valid.
 */
export function validateStep1(fields: Step1Fields): ValidationErrors {
	const errs: ValidationErrors = {};

	if (!fields.profileName.trim()) {
		errs.profileName = 'Profile name is required.';
	} else if (fields.profileName.trim().length > 50) {
		errs.profileName = 'Profile name must be 50 characters or fewer.';
	}

	if (!fields.dateOfBirth) {
		errs.dateOfBirth = 'Date of birth is required.';
	} else {
		const dob = new Date(fields.dateOfBirth);
		const today = new Date();
		today.setHours(0, 0, 0, 0);
		if (isNaN(dob.getTime()) || dob >= today) {
			errs.dateOfBirth = 'Please enter a valid past date.';
		}
	}

	if (!fields.biologicalSex) {
		errs.biologicalSex = 'Biological sex is required.';
	}

	return errs;
}

// ---------------------------------------------------------------------------
// Step 2 — Race Goal
// ---------------------------------------------------------------------------

/**
 * Validates Step 2 (race distance, race date).
 *
 * Returns an object whose keys are field names and values are error messages.
 * An empty object means the step is valid.
 */
export function validateStep2(fields: Step2Fields): ValidationErrors {
	const errs: ValidationErrors = {};

	if (fields.raceDistancePreset === 'custom') {
		const km = parseFloat(fields.raceDistanceCustomKm);
		if (!fields.raceDistanceCustomKm || isNaN(km) || km <= 0) {
			errs.raceDistance = 'Please enter a valid race distance greater than 0 km.';
		}
	}

	if (!fields.raceDate) {
		errs.raceDate = 'Target race date is required.';
	} else {
		const d = new Date(fields.raceDate);
		// Normalize to UTC midnight for a fair date-only comparison
		const todayUtc = new Date();
		todayUtc.setUTCHours(0, 0, 0, 0);
		if (isNaN(d.getTime()) || d <= todayUtc) {
			errs.raceDate = 'Race date must be in the future.';
		}
	}

	return errs;
}

// ---------------------------------------------------------------------------
// Step 3 — Fitness Data
// ---------------------------------------------------------------------------

/**
 * Validates Step 3 (current weekly mileage, longest recent run).
 *
 * When `bulkImportSuccess` is true the fitness fields are optional, so no
 * errors are produced for them.  When it is false they are required.
 *
 * Returns an object whose keys are field names and values are error messages.
 * An empty object means the step is valid.
 */
export function validateStep3(fields: Step3Fields): ValidationErrors {
	const errs: ValidationErrors = {};

	if (!fields.bulkImportSuccess) {
		const wkly = parseFloat(fields.currentWeeklyKm);
		if (!fields.currentWeeklyKm || isNaN(wkly) || wkly < 0) {
			errs.currentWeeklyKm =
				'Current weekly mileage is required (enter 0 if you are just starting).';
		}

		const longest = parseFloat(fields.longestRecentRunKm);
		if (!fields.longestRecentRunKm || isNaN(longest) || longest <= 0) {
			errs.longestRecentRunKm = 'Longest recent run distance is required.';
		}
	}

	return errs;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Returns true when the validation errors object contains no entries. */
export function isValid(errors: ValidationErrors): boolean {
	return Object.keys(errors).length === 0;
}
