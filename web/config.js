"use strict";

/* Public Supabase config for the browser. The anon (publishable) key is designed
   to be exposed client-side — every request it authorizes is still gated by RLS
   and by our own /api ownership checks. Safe to commit. */
window.SKORE_CONFIG = {
  url: "https://xhnstwjlswjoyhxgljjn.supabase.co",
  anonKey:
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhobnN0d2psc3dqb3loeGdsampuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODI5OTExNjEsImV4cCI6MjA5ODU2NzE2MX0.KMiSaDliyEmMnVgdiDnVMnNqW05RsazclDwjXPEVVBQ",
};
