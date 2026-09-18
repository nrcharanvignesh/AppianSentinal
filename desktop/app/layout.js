import './globals.css';

export const metadata = {
  title: 'Appian Sentinel',
  description: 'Agentic Appian development automation — desktop',
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
