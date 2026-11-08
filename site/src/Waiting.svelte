<script lang="ts">
  // The Commission's hourglass (its logo, as in the favicon), turned over at once and then again and again while
  // results are fetched, with a short message. It stands still for readers who ask their system for less motion.
  // The turning is a plain element's transform on a layer of its own, which the browser animates apart from the
  // page's thread: Pagefind computes on that thread for seconds, and an SVG drawing turned there froze after a turn.
  let { message, large = false }: { message: string; large?: boolean } = $props();
</script>

<p class="waiting" class:large role="status" aria-live="polite">
  <span class="hourglass" aria-hidden="true"><svg viewBox="80 -2 57 114">
    <path fill="#F36F3A" d="M133.8,92.6c-1.8,9.6-7.8,17.6-25.3,17.6c-17,0-23.5-8-25.3-17.7c-1.8-9.6,1.5-21,12.8-27.9 c4.8-3,7.8-5.7,9.6-8c0.1-0.2,0.2-0.3,0.4-0.5c-0.1-0.3-0.1-0.5-0.1-0.8c0-1.2,0.8-2.2,2-2.5v22.9c-2.3,0.3-4.1,2.3-4.1,4.7 c0,2.6,2.1,4.7,4.7,4.7c2.6,0,4.7-2.1,4.7-4.7c0-2.4-1.8-4.4-4.1-4.7V52.8c1.1,0.3,2,1.3,2,2.5c0,0.3-0.1,0.5-0.1,0.8 c0.1,0.2,0.2,0.3,0.4,0.5c1.8,2.3,4.8,5.1,9.6,8C132.3,71.6,135.6,82.9,133.8,92.6L133.8,92.6z" />
    <path fill="#005F2A" d="M133.8,17.7c-1.8-9.6-7.8-17.6-25.3-17.6c-17,0-23.5,8-25.3,17.7c-1.8,9.6,1.5,21,12.8,27.9 c4.8,3,7.8,5.7,9.6,8c0.1,0.2,0.2,0.3,0.4,0.5c-0.1,0.3-0.1,0.5-0.1,0.8c0,1.2,0.8,2.2,2,2.5V34.5c-2.3-0.3-4.1-2.3-4.1-4.7 c0-2.6,2.1-4.7,4.7-4.7c2.6,0,4.7,2.1,4.7,4.7c0,2.4-1.8,4.4-4.1,4.7v22.9c1.1-0.3,2-1.3,2-2.5c0-0.3-0.1-0.5-0.1-0.8 c0.1-0.2,0.2-0.3,0.4-0.5c1.8-2.3,4.8-5.1,9.6-8C132.3,38.7,135.6,27.3,133.8,17.7L133.8,17.7z" />
  </svg></span>
  <span>{message}</span>
</p>
