import './globals.css';
import './workbench.css';

export const metadata = {
  title: 'Appian Sentinel',
  description: 'Appian development workbench for desktop',
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
