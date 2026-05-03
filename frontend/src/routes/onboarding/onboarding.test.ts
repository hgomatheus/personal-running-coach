/**
 * Unit tests for onboarding form validation logic.
 *
 * Tests cover:
 *  - Step 1: profile name, date of birth, biological sex (always required)
 *  - Step 2: race goal distance and date (always required)
 *  - Step 3: fitness fields required when no bulk import, optional when bulk import provided
 *  - Form submission prevention when required fields are missing
 *  - Form submission success when all required fields are present
 */

import { describe, it, expect } from 'vitest';
import {
	validateStep1,
	validateStep2,
	validateStep3,
	isValid,
	type Step1Fields,
	type Step2Fields,
	type Step3Fields
} from '$lib/onboardingValidation';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Returns a date string for a date N days from today (positive = future). */
function dateOffset(days: number): string {
	const d = new Date();
	d.setUTCHours(0, 0, 0, 0);
	d.setUTCDate(d.getUTCDate() + days);
	return d.toISOString().split('T')[0];
}

const PAST_DATE = dateOffset(-365 * 25); // 25 years ago — valid DOB
const FUTURE_DATE = dateOffset(180); // 6 months from now — valid race date
const TODAY = dateOffset(0);
const YESTERDAY = dateOffset(-1);

// ---------------------------------------------------------------------------
// Step 1 — Profile Setup
// ---------------------------------------------------------------------------

describe('validateStep1', () => {
	const validFields: Step1Fields = {
		profileName: 'Alice',
		dateOfBirth: PAST_DATE,
		biologicalSex: 'female'
	};

	it('returns no errors for valid input', () => {
		expect(isValid(validateStep1(validFields))).toBe(true);
	});

	// Profile name
	it('requires profile name', () => {
		const errs = validateStep1({ ...validFields, profileName: '' });
		expect(errs.profileName).toBeDefined();
	});

	it('requires profile name (whitespace only)', () => {
		const errs = validateStep1({ ...validFields, profileName: '   ' });
		expect(errs.profileName).toBeDefined();
	});

	it('rejects profile name longer than 50 characters', () => {
		const errs = validateStep1({ ...validFields, profileName: 'A'.repeat(51) });
		expect(errs.profileName).toBeDefined();
	});

	it('accepts profile name of exactly 50 characters', () => {
		const errs = validateStep1({ ...validFields, profileName: 'A'.repeat(50) });
		expect(errs.profileName).toBeUndefined();
	});

	// Date of birth
	it('requires date of birth', () => {
		const errs = validateStep1({ ...validFields, dateOfBirth: '' });
		expect(errs.dateOfBirth).toBeDefined();
	});

	it('rejects a future date of birth', () => {
		const errs = validateStep1({ ...validFields, dateOfBirth: FUTURE_DATE });
		expect(errs.dateOfBirth).toBeDefined();
	});

	it('rejects today as date of birth', () => {
		const errs = validateStep1({ ...validFields, dateOfBirth: TODAY });
		expect(errs.dateOfBirth).toBeDefined();
	});

	it('accepts a past date of birth', () => {
		const errs = validateStep1({ ...validFields, dateOfBirth: PAST_DATE });
		expect(errs.dateOfBirth).toBeUndefined();
	});

	// Biological sex
	it('requires biological sex', () => {
		const errs = validateStep1({ ...validFields, biologicalSex: '' });
		expect(errs.biologicalSex).toBeDefined();
	});

	it('accepts "male"', () => {
		const errs = validateStep1({ ...validFields, biologicalSex: 'male' });
		expect(errs.biologicalSex).toBeUndefined();
	});

	it('accepts "female"', () => {
		const errs = validateStep1({ ...validFields, biologicalSex: 'female' });
		expect(errs.biologicalSex).toBeUndefined();
	});

	it('accepts "other"', () => {
		const errs = validateStep1({ ...validFields, biologicalSex: 'other' });
		expect(errs.biologicalSex).toBeUndefined();
	});

	// All fields missing
	it('reports all three errors when all fields are empty', () => {
		const errs = validateStep1({ profileName: '', dateOfBirth: '', biologicalSex: '' });
		expect(errs.profileName).toBeDefined();
		expect(errs.dateOfBirth).toBeDefined();
		expect(errs.biologicalSex).toBeDefined();
		expect(isValid(errs)).toBe(false);
	});
});

// ---------------------------------------------------------------------------
// Step 2 — Race Goal
// ---------------------------------------------------------------------------

describe('validateStep2', () => {
	const validPresetFields: Step2Fields = {
		raceDistancePreset: 5000,
		raceDistanceCustomKm: '',
		raceDate: FUTURE_DATE
	};

	it('returns no errors for a preset distance with a future race date', () => {
		expect(isValid(validateStep2(validPresetFields))).toBe(true);
	});

	// Race date
	it('requires race date', () => {
		const errs = validateStep2({ ...validPresetFields, raceDate: '' });
		expect(errs.raceDate).toBeDefined();
	});

	it('rejects today as race date', () => {
		const errs = validateStep2({ ...validPresetFields, raceDate: TODAY });
		expect(errs.raceDate).toBeDefined();
	});

	it('rejects a past race date', () => {
		const errs = validateStep2({ ...validPresetFields, raceDate: YESTERDAY });
		expect(errs.raceDate).toBeDefined();
	});

	it('accepts a future race date', () => {
		const errs = validateStep2({ ...validPresetFields, raceDate: FUTURE_DATE });
		expect(errs.raceDate).toBeUndefined();
	});

	// Custom distance
	it('requires custom distance when preset is "custom"', () => {
		const errs = validateStep2({
			raceDistancePreset: 'custom',
			raceDistanceCustomKm: '',
			raceDate: FUTURE_DATE
		});
		expect(errs.raceDistance).toBeDefined();
	});

	it('rejects zero custom distance', () => {
		const errs = validateStep2({
			raceDistancePreset: 'custom',
			raceDistanceCustomKm: '0',
			raceDate: FUTURE_DATE
		});
		expect(errs.raceDistance).toBeDefined();
	});

	it('rejects negative custom distance', () => {
		const errs = validateStep2({
			raceDistancePreset: 'custom',
			raceDistanceCustomKm: '-5',
			raceDate: FUTURE_DATE
		});
		expect(errs.raceDistance).toBeDefined();
	});

	it('rejects non-numeric custom distance', () => {
		const errs = validateStep2({
			raceDistancePreset: 'custom',
			raceDistanceCustomKm: 'abc',
			raceDate: FUTURE_DATE
		});
		expect(errs.raceDistance).toBeDefined();
	});

	it('accepts a valid positive custom distance', () => {
		const errs = validateStep2({
			raceDistancePreset: 'custom',
			raceDistanceCustomKm: '15',
			raceDate: FUTURE_DATE
		});
		expect(errs.raceDistance).toBeUndefined();
	});

	it('does not validate custom distance when a preset is selected', () => {
		// raceDistanceCustomKm is irrelevant when preset is not 'custom'
		const errs = validateStep2({
			raceDistancePreset: 10000,
			raceDistanceCustomKm: '',
			raceDate: FUTURE_DATE
		});
		expect(errs.raceDistance).toBeUndefined();
	});

	// Both fields missing
	it('reports both errors when race date is missing and custom distance is invalid', () => {
		const errs = validateStep2({
			raceDistancePreset: 'custom',
			raceDistanceCustomKm: '',
			raceDate: ''
		});
		expect(errs.raceDistance).toBeDefined();
		expect(errs.raceDate).toBeDefined();
		expect(isValid(errs)).toBe(false);
	});
});

// ---------------------------------------------------------------------------
// Step 3 — Fitness Data (no bulk import)
// ---------------------------------------------------------------------------

describe('validateStep3 — without bulk import', () => {
	const noBulkImport = false;

	it('returns no errors when both fitness fields are provided', () => {
		const errs = validateStep3({
			currentWeeklyKm: '30',
			longestRecentRunKm: '15',
			bulkImportSuccess: noBulkImport
		});
		expect(isValid(errs)).toBe(true);
	});

	it('accepts 0 for current weekly mileage (just starting out)', () => {
		const errs = validateStep3({
			currentWeeklyKm: '0',
			longestRecentRunKm: '5',
			bulkImportSuccess: noBulkImport
		});
		expect(errs.currentWeeklyKm).toBeUndefined();
	});

	it('requires current weekly mileage when no bulk import', () => {
		const errs = validateStep3({
			currentWeeklyKm: '',
			longestRecentRunKm: '15',
			bulkImportSuccess: noBulkImport
		});
		expect(errs.currentWeeklyKm).toBeDefined();
	});

	it('rejects negative current weekly mileage', () => {
		const errs = validateStep3({
			currentWeeklyKm: '-5',
			longestRecentRunKm: '15',
			bulkImportSuccess: noBulkImport
		});
		expect(errs.currentWeeklyKm).toBeDefined();
	});

	it('rejects non-numeric current weekly mileage', () => {
		const errs = validateStep3({
			currentWeeklyKm: 'abc',
			longestRecentRunKm: '15',
			bulkImportSuccess: noBulkImport
		});
		expect(errs.currentWeeklyKm).toBeDefined();
	});

	it('requires longest recent run when no bulk import', () => {
		const errs = validateStep3({
			currentWeeklyKm: '30',
			longestRecentRunKm: '',
			bulkImportSuccess: noBulkImport
		});
		expect(errs.longestRecentRunKm).toBeDefined();
	});

	it('rejects zero longest recent run', () => {
		const errs = validateStep3({
			currentWeeklyKm: '30',
			longestRecentRunKm: '0',
			bulkImportSuccess: noBulkImport
		});
		expect(errs.longestRecentRunKm).toBeDefined();
	});

	it('rejects negative longest recent run', () => {
		const errs = validateStep3({
			currentWeeklyKm: '30',
			longestRecentRunKm: '-1',
			bulkImportSuccess: noBulkImport
		});
		expect(errs.longestRecentRunKm).toBeDefined();
	});

	it('reports both errors when both fitness fields are missing', () => {
		const errs = validateStep3({
			currentWeeklyKm: '',
			longestRecentRunKm: '',
			bulkImportSuccess: noBulkImport
		});
		expect(errs.currentWeeklyKm).toBeDefined();
		expect(errs.longestRecentRunKm).toBeDefined();
		expect(isValid(errs)).toBe(false);
	});
});

// ---------------------------------------------------------------------------
// Step 3 — Fitness Data (with bulk import)
// ---------------------------------------------------------------------------

describe('validateStep3 — with bulk import', () => {
	const withBulkImport = true;

	it('returns no errors even when both fitness fields are empty', () => {
		const errs = validateStep3({
			currentWeeklyKm: '',
			longestRecentRunKm: '',
			bulkImportSuccess: withBulkImport
		});
		expect(isValid(errs)).toBe(true);
	});

	it('returns no errors when fitness fields are provided alongside bulk import', () => {
		const errs = validateStep3({
			currentWeeklyKm: '30',
			longestRecentRunKm: '15',
			bulkImportSuccess: withBulkImport
		});
		expect(isValid(errs)).toBe(true);
	});

	it('does not require current weekly mileage when bulk import is present', () => {
		const errs = validateStep3({
			currentWeeklyKm: '',
			longestRecentRunKm: '15',
			bulkImportSuccess: withBulkImport
		});
		expect(errs.currentWeeklyKm).toBeUndefined();
	});

	it('does not require longest recent run when bulk import is present', () => {
		const errs = validateStep3({
			currentWeeklyKm: '30',
			longestRecentRunKm: '',
			bulkImportSuccess: withBulkImport
		});
		expect(errs.longestRecentRunKm).toBeUndefined();
	});
});

// ---------------------------------------------------------------------------
// Form submission prevention / success (integration of all steps)
// ---------------------------------------------------------------------------

describe('form submission gate', () => {
	it('prevents submission when step 1 has errors', () => {
		// Missing profile name — step 1 invalid
		const errs = validateStep1({ profileName: '', dateOfBirth: PAST_DATE, biologicalSex: 'male' });
		expect(isValid(errs)).toBe(false);
	});

	it('prevents submission when step 2 has errors', () => {
		// Missing race date — step 2 invalid
		const errs = validateStep2({ raceDistancePreset: 5000, raceDistanceCustomKm: '', raceDate: '' });
		expect(isValid(errs)).toBe(false);
	});

	it('prevents submission when step 3 has errors (no bulk import, missing fitness fields)', () => {
		const errs = validateStep3({
			currentWeeklyKm: '',
			longestRecentRunKm: '',
			bulkImportSuccess: false
		});
		expect(isValid(errs)).toBe(false);
	});

	it('allows submission when all steps are valid without bulk import', () => {
		const s1 = validateStep1({
			profileName: 'Bob',
			dateOfBirth: PAST_DATE,
			biologicalSex: 'male'
		});
		const s2 = validateStep2({
			raceDistancePreset: 42195,
			raceDistanceCustomKm: '',
			raceDate: FUTURE_DATE
		});
		const s3 = validateStep3({
			currentWeeklyKm: '50',
			longestRecentRunKm: '25',
			bulkImportSuccess: false
		});

		expect(isValid(s1)).toBe(true);
		expect(isValid(s2)).toBe(true);
		expect(isValid(s3)).toBe(true);
	});

	it('allows submission when all steps are valid with bulk import (fitness fields empty)', () => {
		const s1 = validateStep1({
			profileName: 'Carol',
			dateOfBirth: PAST_DATE,
			biologicalSex: 'female'
		});
		const s2 = validateStep2({
			raceDistancePreset: 'custom',
			raceDistanceCustomKm: '12',
			raceDate: FUTURE_DATE
		});
		const s3 = validateStep3({
			currentWeeklyKm: '',
			longestRecentRunKm: '',
			bulkImportSuccess: true
		});

		expect(isValid(s1)).toBe(true);
		expect(isValid(s2)).toBe(true);
		expect(isValid(s3)).toBe(true);
	});
});
