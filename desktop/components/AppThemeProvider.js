'use client';

import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { createTheme, CssBaseline, ThemeProvider } from '@mui/material';

const STORAGE_KEY = 'appian-sentinel-theme';
const AppThemeContext = createContext(null);

const palettes = {
  dark: {
    mode: 'dark',
    primary: { main: '#4ea1d3' },
    background: { default: '#111820', paper: '#18222d' },
    text: { primary: '#e8eef3', secondary: '#9eacb9' },
    divider: '#33414e',
  },
  light: {
    mode: 'light',
    primary: { main: '#1d6597' },
    background: { default: '#f4f6f8', paper: '#ffffff' },
    text: { primary: '#24292f', secondary: '#66727e' },
    divider: '#d8dde3',
  },
};

export function useAppTheme() {
  const value = useContext(AppThemeContext);
  if (!value) throw new Error('useAppTheme must be used inside AppThemeProvider');
  return value;
}

export default function AppThemeProvider({ children }) {
  const [mode, setMode] = useState('dark');
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved === 'light' || saved === 'dark') setMode(saved);
    setLoaded(true);
  }, []);

  useEffect(() => {
    if (!loaded) return;
    document.documentElement.dataset.theme = mode;
    document.documentElement.style.colorScheme = mode;
    window.localStorage.setItem(STORAGE_KEY, mode);
  }, [loaded, mode]);

  const theme = useMemo(() => createTheme({
    palette: palettes[mode],
    shape: { borderRadius: 3 },
    typography: {
      fontFamily: '"Segoe UI", Arial, sans-serif',
      fontSize: 13,
      button: { textTransform: 'none', fontWeight: 600 },
    },
    components: {
      MuiCssBaseline: {
        styleOverrides: {
          body: { overflow: 'hidden' },
        },
      },
      MuiTooltip: {
        defaultProps: { arrow: true },
      },
    },
  }), [mode]);

  const value = useMemo(() => ({
    mode,
    toggleMode: () => setMode((current) => (current === 'dark' ? 'light' : 'dark')),
  }), [mode]);

  return (
    <AppThemeContext.Provider value={value}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        {children}
      </ThemeProvider>
    </AppThemeContext.Provider>
  );
}
