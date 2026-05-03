/**
 * Unit tests for manual run entry form validation logic.
 *
 * Tests cover:
 *  - Date is required
 *  - Distance must be > 0 km (reject 0, negative, non-numeric, empty)
 *  - Duration must be > 0 (reject 0, negative, non-numeric, empty)
 *  - Heart rate is optional (no error when empty)
 *  - Heart rate must be a valid number when provided (30–250 bpm range)
 *  - Notes are optional
 *  - Form submission is prevented when required fields are invalid
 *  - Form submission succeeds when all required fields are valid
 */

import { describe, it, expect } from 'vitest';
import {
	validateRunForm,
	parseDuration,
	isValid,
	type RunFormFields
} from './runFormValidation';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Returns a minimal valid set of run form fields. */
function validFields(overrides: Partial<RunFormFields> = {}): RunFormFields {
	return {
		date: '2024-06-15',
		distanceKm: '10',
		duration: '52:30',
		avgHeartRate: '',
		notes: '',
		...overrides
	};
}

// ---------------------------------------------------------------------------
// parseDuration
// ---------------------------------------------------------------------------

describe('parseDuration', () => {
	it('parses mm:ss format', () => {
		expect(parseDuration('52:30')).toBe(52 * 60 + 30);
	});

	it('parses hh:mm:ss format', () => {
		expect(parseDuration('1:05:00')).toBe(3600 + 5 * 60);
	});

	it('parses 0:00 as 0 seconds', () => {
		expect(parseDuration('0:00')).toBe(0);
	});

	it('returns null for plain number', () => {
		expect(parseDuration('3600')).toBeNull();
	});

	it('returns null for invalid format', () => {
		expect(parseDuration('abc')).toBeNull();
	});

	it('returns null for empty string', () => {
		expect(parseDuration('')).toBeNull();
	});

	it('returns null for seconds out of range (e.g. 52:60)', () => {
		expect(parseDuration('52:60')).toBeNull();
	});

	it('handles leading zeros in mm:ss', () => {
		expect(parseDuration('05:09')).toBe(5 * 60 + 9);
	});
});

// ---------------------------------------------------------------------------
// Date validation
// ---------------------------------------------------------------------------

describe('validateRunForm — date', () => {
	it('returns no date error when date is provided', () => {
		const errs = validateRunForm(validFields());
		expect(errs.date).toBeUndefined();
	});

	it('requires date', () => {
		const errs = validateRunForm(validFields({ date: '' }));
		expect(errs.date).toBeDefined();
	});
});

// ---------------------------------------------------------------------------
// Distance validation
// ---------------------------------------------------------------------------

describe('validateRunForm — distance', () => {
	it('accepts a valid positive distance', () => {
		const errs = validateRunForm(validFields({ distanceKm: '10.5' }));
		expect(errs.distanceKm).toBeUndefined();
	});

	it('requires distance (empty string)', () => {
		const errs = validateRunForm(validFields({ distanceKm: '' }));
		expect(errs.distanceKm).toBeDefined();
	});

	it('requires distance (whitespace only)', () => {
		const errs = validateRunForm(validFields({ distanceKm: '   ' }));
		expect(errs.distanceKm).toBeDefined();
	});

	it('rejects distance of 0', () => {
		const errs = validateRunForm(validFields({ distanceKm: '0' }));
		expect(errs.distanceKm).toBeDefined();
	});

	it('rejects negative distance', () => {
		const errs = validateRunForm(validFields({ distanceKm: '-5' }));
		expect(errs.distanceKm).toBeDefined();
	});

	it('rejects non-numeric distance', () => {
		const errs = validateRunForm(validFields({ distanceKm: 'abc' }));
		expect(errs.distanceKm).toBeDefined();
	});

	it('accepts very small positive distance', () => {
		const errs = validateRunForm(validFields({ distanceKm: '0.01' }));
		expect(errs.distanceKm).toBeUndefined();
	});
});

// ---------------------------------------------------------------------------
// Duration validation
// ---------------------------------------------------------------------------

describe('validateRunForm — duration', () => {
	it('accepts a valid mm:ss duration', () => {
		const errs = validateRunForm(validFields({ duration: '45:30' }));
		expect(errs.duration).toBeUndefined();
	});

	it('accepts a valid hh:mm:ss duration', () => {
		const errs = validateRunForm(validFields({ duration: '1:05:00' }));
		expect(errs.duration).toBeUndefined();
	});

	it('requires duration (empty string)', () => {
		const errs = validateRunForm(validFields({ duration: '' }));
		expect(errs.duration).toBeDefined();
	});

	it('requires duration (whitespace only)', () => {
		const errs = validateRunForm(validFields({ duration: '   ' }));
		expect(errs.duration).toBeDefined();
	});

	it('rejects non-numeric duration', () => {
		const errs = validateRunForm(validFields({ duration: 'abc' }));
		expect(errs.duration).toBeDefined();
	});

	it('rejects plain number (no colon separator)', () => {
		const errs = validateRunForm(validFields({ duration: '3600' }));
		expect(errs.duration).toBeDefined();
	});

	it('rejects duration of 0:00 (zero seconds)', () => {
		const errs = validateRunForm(validFields({ duration: '0:00' }));
		expect(errs.duration).toBeDefined();
	});

	it('rejects duration with seconds out of range (52:60)', () => {
		const errs = validateRunForm(validFields({ duration: '52:60' }));
		expect(errs.duration).toBeDefined();
	});
});

// ---------------------------------------------------------------------------
// Heart rate validation (optional field)
// ---------------------------------------------------------------------------

describe('validateRunForm — heart rate', () => {
	it('produces no error when heart rate is empty (optional)', () => {
		const errs = validateRunForm(validFields({ avgHeartRate: '' }));
		expect(errs.avgHeartRate).toBeUndefined();
	});

	it('produces no error when heart rate is whitespace only (treated as empty)', () => {
		const errs = validateRunForm(validFields({ avgHeartRate: '   ' }));
		expect(errs.avgHeartRate).toBeUndefined();
	});

	it('accepts a valid heart rate of 155', () => {
		const errs = validateRunForm(validFields({ avgHeartRate: '155' }));
		expect(errs.avgHeartRate).toBeUndefined();
	});

	it('accepts the lower boundary of 30 bpm', () => {
		const errs = validateRunForm(validFields({ avgHeartRate: '30' }));
		expect(errs.avgHeartRate).toBeUndefined();
	});

	it('accepts the upper boundary of 250 bpm', () => {
		const errs = validateRunForm(validFields({ avgHeartRate: '250' }));
		expect(errs.avgHeartRate).toBeUndefined();
	});

	it('rejects heart rate below 30 bpm', () => {
		const errs = validateRunForm(validFields({ avgHeartRate: '29' }));
		expect(errs.avgHeartRate).toBeDefined();
	});

	it('rejects heart rate above 250 bpm', () => {
		const errs = validateRunForm(validFields({ avgHeartRate: '251' }));
		expect(errs.avgHeartRate).toBeDefined();
	});

	it('rejects non-numeric heart rate', () => {
		const errs = validateRunForm(validFields({ avgHeartRate: 'fast' }));
		expect(errs.avgHeartRate).toBeDefined();
	});

	it('rejects heart rate of 0', () => {
		const errs = validateRunForm(validFields({ avgHeartRate: '0' }));
		expect(errs.avgHeartRate).toBeDefined();
	});
});

// ---------------------------------------------------------------------------
// Notes validation (always optional)
// ---------------------------------------------------------------------------

describe('validateRunForm — notes', () => {
	it('produces no error when notes is empty', () => {
		const errs = validateRunForm(validFields({ notes: '' }));
		expect(errs.notes).toBeUndefined();
	});

	it('produces no error when notes has content', () => {
		const errs = validateRunForm(validFields({ notes: 'Felt great today!' }));
		expect(errs.notes).toBeUndefined();
	});
});

// ---------------------------------------------------------------------------
// Form submission gate
// ---------------------------------------------------------------------------

describe('form submission gate', () => {
	it('prevents submission when date is missing', () => {
		const errs = validateRunForm(validFields({ date: '' }));
		expect(isValid(errs)).toBe(false);
	});

	it('prevents submission when distance is missing', () => {
		const errs = validateRunForm(validFields({ distanceKm: '' }));
		expect(isValid(errs)).toBe(false);
	});

	it('prevents submission when distance is 0', () => {
		const errs = validateRunForm(validFields({ distanceKm: '0' }));
		expect(isValid(errs)).toBe(false);
	});

	it('prevents submission when duration is missing', () => {
		const errs = validateRunForm(validFields({ duration: '' }));
		expect(isValid(errs)).toBe(false);
	});

	it('prevents submission when duration format is invalid', () => {
		const errs = validateRunForm(validFields({ duration: 'not-a-time' }));
		expect(isValid(errs)).toBe(false);
	});

	it('prevents submission when heart rate is out of range', () => {
		const errs = validateRunForm(validFields({ avgHeartRate: '300' }));
		expect(isValid(errs)).toBe(false);
	});

	it('reports all required-field errors when all required fields are empty', () => {
		const errs = validateRunForm({ date: '', distanceKm: '', duration: '', avgHeartRate: '', notes: '' });
		expect(errs.date).toBeDefined();
		expect(errs.distanceKm).toBeDefined();
		expect(errs.duration).toBeDefined();
		expect(isValid(errs)).toBe(false);
	});

	it('allows submission when all required fields are valid (no optional fields)', () => {
		const errs = validateRunForm(validFields());
		expect(isValid(errs)).toBe(true);
	});

	it('allows submission when all fields including optional ones are valid', () => {
		const errs = validateRunForm(validFields({ avgHeartRate: '155', notes: 'Good run' }));
		expect(isValid(errs)).toBe(true);
	});

	it('allows submission when optional heart rate is empty', () => {
		const errs = validateRunForm(validFields({ avgHeartRate: '' }));
		expect(isValid(errs)).toBe(true);
	});

	it('allows submission when optional notes is empty', () => {
		const errs = validateRunForm(validFields({ notes: '' }));
		expect(isValid(errs)).toBe(true);
	});
});
