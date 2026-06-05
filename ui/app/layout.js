import "./globals.css";

export const metadata = {
  title: "OCI RAG Agent",
  description: "Reference chat UI for the OCI RAG Agent Blueprint"
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
