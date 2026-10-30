/* Where the form's server lives.

   `api: ""` means the same address as this page: the worker (site/_worker.js)
   answers /api/onboarding/* on this host, so the page calls itself. Moving the
   form to a new domain needs no change here. */
window.ONBOARDING_FORM = {
  api: "",
  route: "/api/onboarding"
};
