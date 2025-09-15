import "./globals.css";
import Navbar from "./components/Navbar";
import { AuthProvider } from "./providers/AuthProvider";

export const metadata = { title: "Reelay" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-white text-neutral-900 antialiased">
        <AuthProvider>
          <Navbar />
          {children}
        </AuthProvider>
      </body>
    </html>
  );
}