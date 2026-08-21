/* Copy to mapbox-token.js (gitignored) and set your Mapbox public token.
   route.html reads window.MAPBOX_TOKEN from it; without it the map shows a
   message and the rest of the page still works.

   The token cannot be committed: GitHub push protection on this repo rejects
   Mapbox tokens. For the Vercel deploy, create mapbox-token.js in the build or
   paste the token in directly on a branch you do not push. */
window.MAPBOX_TOKEN = "pk.your-mapbox-public-token-here";
