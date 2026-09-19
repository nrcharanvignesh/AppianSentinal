'use client';

import { useState } from 'react';
import ArrowBackOutlinedIcon from '@mui/icons-material/ArrowBackOutlined';
import AppsOutlinedIcon from '@mui/icons-material/AppsOutlined';
import MenuOutlinedIcon from '@mui/icons-material/MenuOutlined';
import PersonOutlineOutlinedIcon from '@mui/icons-material/PersonOutlineOutlined';
import SearchOutlinedIcon from '@mui/icons-material/SearchOutlined';
import SettingsOutlinedIcon from '@mui/icons-material/SettingsOutlined';

function HeaderMenu({ label, items, icon }) {
  if (!items?.length) return null;

  return (
    <details className="designer-header-menu">
      <summary aria-label={label} title={label}>
        {icon}
      </summary>
      <ul role="menu" aria-label={label}>
        {items.map((item, index) => {
          const normalized = typeof item === 'string' ? { label: item } : item;
          const key = normalized.id || normalized.label || index;
          return (
            <li key={key} role="none">
              {normalized.href ? (
                <a role="menuitem" href={normalized.href}>
                  {normalized.label}
                </a>
              ) : (
                <button
                  type="button"
                  role="menuitem"
                  disabled={normalized.disabled}
                  onClick={normalized.onSelect}
                >
                  {normalized.label}
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </details>
  );
}

export default function DesignerHeader({
  appName,
  onBack,
  onSearch,
  settingsItems,
  navigationItems,
  userItems,
}) {
  const [term, setTerm] = useState('');

  function submitSearch(event) {
    event.preventDefault();
    onSearch(term);
  }

  return (
    <header className="designer-header">
      <div className="designer-header-context">
        {onBack && (
          <button
            className="designer-header-icon-button"
            type="button"
            aria-label="Back"
            title="Back"
            onClick={onBack}
          >
            <ArrowBackOutlinedIcon aria-hidden="true" />
          </button>
        )}
        <span className="designer-context-icon" aria-hidden="true">
          <AppsOutlinedIcon />
        </span>
        <span className="designer-app-name">{appName}</span>
      </div>

      <div className="designer-header-actions">
        <form className="designer-quick-search" role="search" onSubmit={submitSearch}>
          <label className="designer-sr-only" htmlFor="designer-quick-search">
            Quick search
          </label>
          <input
            id="designer-quick-search"
            type="search"
            value={term}
            placeholder="Quick search"
            onChange={(event) => setTerm(event.target.value)}
          />
          <button type="submit" aria-label="Search" title="Search">
            <SearchOutlinedIcon aria-hidden="true" />
          </button>
        </form>
        <HeaderMenu
          label="Settings menu"
          items={settingsItems}
          icon={<SettingsOutlinedIcon aria-hidden="true" />}
        />
        <HeaderMenu
          label="Navigation menu"
          items={navigationItems}
          icon={<MenuOutlinedIcon aria-hidden="true" />}
        />
        <HeaderMenu
          label="User menu"
          items={userItems}
          icon={<PersonOutlineOutlinedIcon aria-hidden="true" />}
        />
      </div>
    </header>
  );
}
