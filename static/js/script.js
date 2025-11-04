// Toggle Mobile Navbar
function toggleMenu() {
  document.getElementById("navLinks").classList.toggle("active");
}

// Footer year auto update
document.getElementById("year").textContent = new Date().getFullYear();

// Login Validation
const loginForm = document.getElementById("loginForm");
if (loginForm) {
  loginForm.addEventListener("submit", function (e) {
    e.preventDefault();
    const user = document.getElementById("username").value.trim();
    const pass = document.getElementById("password").value.trim();

    if (user === "" || pass === "") {
      alert("Please fill in both fields.");
    } else {
      alert("Login successful (demo only)!");
      window.location.href = "index.html";
    }
  });
}
