// AGPL-3.0-or-later. Derived from the receive verification bridge.
package main

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/base64"
	"errors"
	"github.com/mattn/go-sqlite3"
)

func snapshot(db *sql.DB) ([]byte, error) {
	conn, err := db.Conn(context.Background())
	if err != nil {
		return nil, err
	}
	defer conn.Close()
	var data []byte
	err = conn.Raw(func(raw any) error { var e error; data, e = raw.(*sqlite3.SQLiteConn).Serialize("main"); return e })
	return data, err
}
func openMemory(state string) (*sql.DB, error) {
	db, err := sql.Open("sqlite3", ":memory:?_foreign_keys=on")
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(1)
	db.SetMaxIdleConns(1)
	if state != "" {
		data, e := base64.StdEncoding.DecodeString(state)
		if e != nil || len(data) < 100 || !bytes.HasPrefix(data, []byte("SQLite format 3\x00")) {
			db.Close()
			return nil, errors.New("invalid_snapshot")
		}
		conn, e := db.Conn(context.Background())
		if e != nil {
			db.Close()
			return nil, e
		}
		e = conn.Raw(func(raw any) error { return raw.(*sqlite3.SQLiteConn).Deserialize(data, "main") })
		conn.Close()
		if e != nil {
			db.Close()
			return nil, e
		}
	}
	if _, err = db.Exec("PRAGMA temp_store=MEMORY; PRAGMA trusted_schema=OFF"); err != nil {
		db.Close()
		return nil, err
	}
	var check string
	if err = db.QueryRow("PRAGMA quick_check").Scan(&check); err != nil || check != "ok" {
		db.Close()
		return nil, errors.New("invalid_snapshot")
	}
	return db, nil
}
