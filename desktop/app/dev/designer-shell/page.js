'use client';

import { useEffect, useState } from 'react';
import DesignerHeader from '../../../components/DesignerHeader';
import NavigationPane from '../../../components/NavigationPane';
import { useAppTheme } from '../../../components/AppThemeProvider';

export default function DesignerShellHarness() {
  const [active, setActive] = useState('build');
  const [searchTerm, setSearchTerm] = useState('');
  const [hydrated, setHydrated] = useState(false);
  const { mode, toggleMode } = useAppTheme();

  useEffect(() => setHydrated(true), []);

  return (
    <div className="designer-shell" data-hydrated={hydrated}>
      <DesignerHeader
        appName="Sentinel Demo"
        onBack={() => {}}
        onSearch={setSearchTerm}
        settingsItems={[{ id: 'preferences', label: 'Preferences' }]}
        navigationItems={[{ id: 'applications', label: 'Applications' }]}
        userItems={[{ id: 'profile', label: 'Profile' }]}
      />
      <div className="designer-shell-body">
        <NavigationPane
          active={active}
          onNavigate={setActive}
          available={new Set(['explore', 'build'])}
        />
        <main className="designer-shell-content">
          <h1>{active.slice(0, 1).toUpperCase() + active.slice(1)}</h1>
          <p aria-live="polite">Search term: {searchTerm || 'None'}</p>
          <button type="button" onClick={toggleMode}>
            Use {mode === 'dark' ? 'light' : 'dark'} theme
          </button>
        </main>
      </div>
    </div>
  );
}
