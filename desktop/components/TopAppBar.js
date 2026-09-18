'use client';

import { useRef } from 'react';

export default function TopAppBar({ appName, connected, status, onUpload }) {
  const fileRef = useRef(null);

  return (
    <header className="topbar">
      <div className="brand" aria-label="Appian Sentinel">
        <span className="brand-mark" aria-hidden="true">AS</span>
        <span>Appian Sentinel</span>
        <span className="workspace-name">{appName || 'No application loaded'}</span>
      </div>
      <div className="topbar-actions">
        <span className={`connection ${connected ? 'is-online' : ''}`}>
          <span className="connection-dot" aria-hidden="true" />
          {connected ? 'Sidecar online' : 'Sidecar offline'}
        </span>
        <span className="status-pill">{String(status || 'idle').replaceAll('_', ' ')}</span>
        <button className="primary-button" type="button" onClick={() => fileRef.current?.click()}>
          Import application
        </button>
        <input
          ref={fileRef}
          hidden
          type="file"
          accept=".zip"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) onUpload(file);
            event.target.value = '';
          }}
        />
      </div>
    </header>
  );
}
