BEGIN TRANSACTION;
CREATE TABLE IF NOT EXISTS round (
	round_id	SERIAL UNIQUE,
	starts_at	TIMESTAMPTZ,
	is_finished	BOOLEAN NOT NULL DEFAULT FALSE,
	group_id	INTEGER NOT NULL,
	in_progress 	BOOLEAN NOT NULL DEFAULT FALSE
	);
CREATE TABLE IF NOT EXISTS participant (
	participant_id	SERIAL UNIQUE,
	tg_name		TEXT,
	insta_link	TEXT,
	is_banned	BOOLEAN NOT NULL DEFAULT FALSE,
	ban_warnings	INTEGER NOT NULL DEFAULT 0,
	user_id		INTEGER DEFAULT 0,
	is_pidoras	BOOLEAN NOT NULL DEFAULT FALSE,
	full_name	TEXT NOT NULL
	);
CREATE TABLE user_and_round (
	user_id		INTEGER NOT NULL REFERENCES participant(participant_id),
	round_id	INTEGER NOT NULL REFERENCES round(round_id)
	);
COMMIT;
