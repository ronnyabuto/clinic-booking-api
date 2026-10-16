-- Run after migrations using psql -v ON_ERROR_STOP=1 -f tests/database-probes.sql.
-- All probe records are rolled back.
BEGIN;
INSERT INTO doctors (id, full_name) VALUES ('ffffffff-0000-0000-0000-000000000001', 'Constraint probe');
INSERT INTO patients (id, full_name) VALUES ('ffffffff-0000-0000-0000-000000000002', 'Constraint probe');

DO $probe$
DECLARE
    doctor uuid := 'ffffffff-0000-0000-0000-000000000001';
    patient uuid := 'ffffffff-0000-0000-0000-000000000002';
    first_id uuid := 'ffffffff-0000-0000-0000-000000000003';
    second_id uuid := 'ffffffff-0000-0000-0000-000000000004';
    whitespace text := U&'\0009\000A\000B\000C\000D\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000';
    character text;
    constraint_name text;
    index_number integer;
BEGIN
    INSERT INTO appointments (id, doctor_id, patient_id, slot_start)
    VALUES (first_id, doctor, patient, '2030-01-07 09:00+03');
    BEGIN
        INSERT INTO appointments (id, doctor_id, patient_id, slot_start)
        VALUES (second_id, doctor, patient, '2030-01-07 06:00+00');
        RAISE EXCEPTION 'Duplicate active slot was accepted';
    EXCEPTION WHEN unique_violation THEN
        GET STACKED DIAGNOSTICS constraint_name = CONSTRAINT_NAME;
        IF constraint_name <> 'uq_doctor_active_slot' THEN RAISE; END IF;
    END;

    FOR index_number IN 0..length(whitespace) LOOP
        character := substring(whitespace FROM index_number FOR 1);
        BEGIN
            UPDATE appointments SET status = 'CANCELLED', cancel_reason = character,
                cancelled_at = clock_timestamp() WHERE id = first_id;
            RAISE EXCEPTION 'Blank cancellation reason was accepted';
        EXCEPTION WHEN check_violation THEN
            GET STACKED DIAGNOSTICS constraint_name = CONSTRAINT_NAME;
            IF constraint_name <> 'ck_appointment_cancellation_state' THEN RAISE; END IF;
        END;
    END LOOP;
    BEGIN
        UPDATE appointments SET status = NULL WHERE id = first_id;
        RAISE EXCEPTION 'Null status was accepted';
    EXCEPTION WHEN not_null_violation THEN NULL;
    END;
    BEGIN
        UPDATE appointments SET status = 'UNKNOWN' WHERE id = first_id;
        RAISE EXCEPTION 'Unknown status was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        UPDATE appointments SET cancel_reason = 'Unexpected' WHERE id = first_id;
        RAISE EXCEPTION 'Booked appointment accepted cancellation metadata';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    UPDATE appointments SET status = 'CANCELLED', cancel_reason = 'Changed plans',
        cancelled_at = clock_timestamp() WHERE id = first_id;
    INSERT INTO appointments (id, doctor_id, patient_id, slot_start)
    VALUES (second_id, doctor, patient, '2030-01-07 09:00+03');
    IF (SELECT count(*) FROM appointments WHERE doctor_id = doctor) <> 2 THEN
        RAISE EXCEPTION 'Cancelled history was not retained';
    END IF;

    BEGIN
        INSERT INTO doctor_schedules (id, doctor_id, day_of_week, start_time, end_time)
        VALUES (first_id, doctor, 0, '09:00:00.000001', '12:00');
        RAISE EXCEPTION 'Fractional schedule start was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO doctor_schedules (id, doctor_id, day_of_week, start_time, end_time)
        VALUES (first_id, doctor, 0, '09:00', '12:00:00.000001');
        RAISE EXCEPTION 'Fractional schedule end was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    INSERT INTO doctor_schedules (id, doctor_id, day_of_week, start_time, end_time)
    VALUES (first_id, doctor, 0, '09:00', '12:00'), (second_id, doctor, 0, '12:00', '13:00');
    RAISE NOTICE 'PASS: uniqueness, equivalent offsets, 26 blank reasons, cancellation state, rebooking, history, fractional endpoints and adjacent shifts';
END
$probe$;
ROLLBACK;
