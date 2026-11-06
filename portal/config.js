// Portal settings. These two Supabase values are PUBLIC by design (every visitor's browser
// needs them); the security rules in the database are what protect the data.
// NEVER put the "service_role" key here: that one is secret and stays in your .env only.
window.PORTAL_CONFIG = {
  // Supabase → Project Settings → API → "Project URL"
  supabaseUrl: "https://YOUR-PROJECT-REF.supabase.co",
  // Supabase → Project Settings → API → "anon public" key
  supabaseAnonKey: "YOUR-ANON-PUBLIC-KEY",

  // Free Supabase plan: 50 MB per file. After upgrading to Pro, raise this (e.g. 2000).
  maxUploadMB: 50,

  // Shown in the upload form so affiliates can say which piece is in the clip.
  products: [
    { handle: "onewrld-fall-of-icarus-zip-hoodie", name: "Fall of Icarus Zip Hoodie" },
    { handle: "onewrld-fall-of-icarus-sweatpants", name: "Fall of Icarus Sweatpants" },
    { handle: "onewrld-acid-wash-signature-hat", name: "Acid Wash Signature Hat" },
    { handle: "onewrld-shaker-cup", name: "Shaker Cup" },
  ],
};
