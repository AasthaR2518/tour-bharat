document.documentElement.style.scrollBehavior = "smooth";

function toggleTheme(){
    document.body.classList.toggle("dark");
}
new Swiper(".mySwiper", {
    slidesPerView: 3,
    spaceBetween: 30,
    loop: true,
    centeredSlides: false,

    pagination: {
        el: ".swiper-pagination",
        clickable: true,
    },

    navigation: {
        nextEl: ".swiper-button-next",
        prevEl: ".swiper-button-prev",
    },

    breakpoints: {
        320: {
            slidesPerView: 1,
            spaceBetween: 20,
        },
        768: {
            slidesPerView: 2,
            spaceBetween: 25,
        },
        1024: {
            slidesPerView: 3,
            spaceBetween: 30,
        }
    }
});