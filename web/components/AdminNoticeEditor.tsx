"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

const SECRET_KEY = "rcgls_upload_secret";

type Props = {
  initialContent: string;
};

export default function AdminNoticeEditor({ initialContent }: Props) {
  const [secret, setSecret] = useState("");
  const [content, setContent] = useState(initialContent);
  const [status, setStatus] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [unlocked, setUnlocked] = useState(false);

  useEffect(() => {
    try {
      const saved = sessionStorage.getItem(SECRET_KEY) ?? "";
      if (saved) setSecret(saved);
    } catch {
      // ignore
    }
  }, []);

  function rememberSecret(value: string) {
    setSecret(value);
    try {
      if (value) sessionStorage.setItem(SECRET_KEY, value);
      else sessionStorage.removeItem(SECRET_KEY);
    } catch {
      // ignore
    }
  }

  async function unlock(e: React.FormEvent) {
    e.preventDefault();
    const key = secret.trim();
    if (!key) {
      setStatus("업로드 시크릿을 입력하세요.");
      return;
    }
    setSaving(true);
    setStatus(null);
    try {
      const res = await fetch("/api/notice", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-rcgls-upload-secret": key,
        },
        body: JSON.stringify({ content }),
      });
      const data = (await res.json().catch(() => ({}))) as {
        error?: string;
        notice?: { content?: string };
      };
      if (!res.ok) {
        setUnlocked(false);
        setStatus(data.error || "시크릿이 올바르지 않습니다.");
        return;
      }
      rememberSecret(key);
      if (typeof data.notice?.content === "string") {
        setContent(data.notice.content);
      }
      setUnlocked(true);
      setStatus("인증되었습니다. 공지를 수정할 수 있습니다.");
    } catch {
      setStatus("서버에 연결하지 못했습니다.");
    } finally {
      setSaving(false);
    }
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    const key = secret.trim();
    if (!key) {
      setUnlocked(false);
      setStatus("업로드 시크릿을 다시 입력하세요.");
      return;
    }
    setSaving(true);
    setStatus(null);
    try {
      const res = await fetch("/api/notice", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-rcgls-upload-secret": key,
        },
        body: JSON.stringify({ content }),
      });
      const data = (await res.json().catch(() => ({}))) as {
        error?: string;
        notice?: { content?: string };
      };
      if (!res.ok) {
        if (res.status === 401) setUnlocked(false);
        setStatus(data.error || "저장에 실패했습니다.");
        return;
      }
      if (typeof data.notice?.content === "string") {
        setContent(data.notice.content);
      }
      setStatus("공지사항을 저장했습니다.");
    } catch {
      setStatus("서버에 연결하지 못했습니다.");
    } finally {
      setSaving(false);
    }
  }

  function lock() {
    rememberSecret("");
    setUnlocked(false);
    setStatus("잠갔습니다.");
  }

  return (
    <div className="admin-shell">
      <header className="admin-header">
        <div>
          <p className="admin-kicker">RC Goal Line</p>
          <h1>공지사항 관리</h1>
        </div>
        <Link href="/" className="admin-link">
          기록 화면
        </Link>
      </header>

      {!unlocked ? (
        <form className="admin-card" onSubmit={unlock}>
          <label className="admin-label" htmlFor="upload-secret">
            RCGLS_UPLOAD_SECRET
          </label>
          <input
            id="upload-secret"
            className="admin-input"
            type="password"
            autoComplete="current-password"
            placeholder="업로드 시크릿 입력"
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
          />
          <button className="admin-btn" type="submit" disabled={saving}>
            {saving ? "확인 중…" : "잠금 해제"}
          </button>
          {status ? <p className="admin-status">{status}</p> : null}
        </form>
      ) : (
        <form className="admin-card" onSubmit={save}>
          <label className="admin-label" htmlFor="notice-content">
            공지 내용
          </label>
          <textarea
            id="notice-content"
            className="admin-textarea"
            rows={6}
            maxLength={2000}
            placeholder="홈 화면 상단에 표시할 공지를 입력하세요."
            value={content}
            onChange={(e) => setContent(e.target.value)}
          />
          <p className="admin-hint">
            {content.length} / 2000자 · 비우면 공지 칸이 숨겨집니다.
          </p>
          <div className="admin-actions">
            <button className="admin-btn" type="submit" disabled={saving}>
              {saving ? "저장 중…" : "저장"}
            </button>
            <button
              className="admin-btn admin-btn-ghost"
              type="button"
              onClick={lock}
              disabled={saving}
            >
              잠금
            </button>
          </div>
          {status ? <p className="admin-status">{status}</p> : null}
        </form>
      )}
    </div>
  );
}
