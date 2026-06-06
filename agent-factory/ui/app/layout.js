import "./globals.css";

export const metadata = {
  title: "Agent Factory",
  description: "Guided OCI Enterprise AI RAG agent deployment"
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

