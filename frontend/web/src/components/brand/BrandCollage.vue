<script setup lang="ts">
// The landing's illustration (1C): Tara's own shapes in the brand palette, a
// reel card, a post card, a marketplace card, a story ring and reactions.
// Decorative only: no people, no photos, no third-party artwork.
import { useId } from "vue";

const uid = useId();
const g = (name: string) => `${uid}-${name}`;
</script>

<template>
  <svg viewBox="0 0 560 460" class="h-auto w-full" role="presentation" aria-hidden="true" focusable="false">
    <defs>
      <linearGradient :id="g('brand')" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="#6A00F4" />
        <stop offset="0.55" stop-color="#A855F7" />
        <stop offset="1" stop-color="#FF4ED8" />
      </linearGradient>
      <linearGradient :id="g('night')" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#0B0B1F" />
        <stop offset="1" stop-color="#360080" />
      </linearGradient>
      <linearGradient :id="g('dawn')" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="#E8E6FF" />
        <stop offset="1" stop-color="#FFB8F0" />
      </linearGradient>
      <filter :id="g('shadow')" x="-20%" y="-20%" width="140%" height="140%">
        <feDropShadow dx="0" dy="10" stdDeviation="12" flood-color="#0B0B1F" flood-opacity="0.18" />
      </filter>
      <clipPath :id="g('reel')"><rect x="236" y="40" width="200" height="320" rx="26" /></clipPath>
      <clipPath :id="g('avatar')"><circle cx="420" cy="368" r="46" /></clipPath>
    </defs>

    <!-- Soft brand glow behind everything -->
    <circle cx="300" cy="230" r="190" :fill="`url(#${g('brand')})`" opacity="0.10" />

    <!-- Marketplace card (back, tilted) -->
    <g :filter="`url(#${g('shadow')})`" transform="rotate(-7 170 190)">
      <rect x="86" y="96" width="176" height="196" rx="22" :fill="`url(#${g('dawn')})`" />
      <rect x="104" y="114" width="34" height="34" rx="10" fill="#FFFFFF" opacity="0.9" />
      <path d="M113 126h16l-2 14h-12z" fill="none" stroke="#6A00F4" stroke-width="2.4" stroke-linejoin="round" />
      <path d="M117 126a4 4 0 0 1 8 0" fill="none" stroke="#6A00F4" stroke-width="2.4" />
      <circle cx="184" cy="214" r="44" fill="#A855F7" opacity="0.35" />
      <path d="M150 244c18-30 50-30 68 0z" fill="#6A00F4" opacity="0.55" />
    </g>

    <!-- Reel card (centre) -->
    <g :filter="`url(#${g('shadow')})`">
      <rect x="236" y="40" width="200" height="320" rx="26" :fill="`url(#${g('night')})`" />
      <g :clip-path="`url(#${g('reel')})`">
        <circle cx="380" cy="120" r="34" fill="#FF4ED8" opacity="0.85" />
        <path d="M236 300c40-60 90-80 130-50s70 10 70-10v120H236z" :fill="`url(#${g('brand')})`" />
        <path d="M236 330c50-30 110-40 200-10v40H236z" fill="#E8E6FF" opacity="0.25" />
      </g>
      <rect x="256" y="58" width="160" height="5" rx="2.5" fill="#FFFFFF" opacity="0.3" />
      <rect x="256" y="58" width="72" height="5" rx="2.5" fill="#FFFFFF" />
      <circle cx="336" cy="200" r="26" fill="#FFFFFF" opacity="0.18" />
      <path d="M328 186l22 14-22 14z" fill="#FFFFFF" />
    </g>

    <!-- Time chip on the reel -->
    <g :filter="`url(#${g('shadow')})`">
      <rect x="392" y="88" width="78" height="34" rx="17" fill="#6A00F4" />
      <circle cx="412" cy="105" r="8" fill="none" stroke="#FFFFFF" stroke-width="2.4" />
      <path d="M412 100v5l3 3" fill="none" stroke="#FFFFFF" stroke-width="2.4" stroke-linecap="round" />
      <rect x="426" y="101" width="32" height="8" rx="4" fill="#FFFFFF" opacity="0.85" />
    </g>

    <!-- Post card (front left) -->
    <g :filter="`url(#${g('shadow')})`">
      <rect x="132" y="228" width="172" height="196" rx="22" class="fill-white dark:fill-gray-900" />
      <rect x="148" y="244" width="30" height="30" rx="9" fill="#6A00F4" />
      <path d="M163 251l3 6 6.5 1-4.7 4.5 1.1 6.5-5.9-3.1-5.9 3.1 1.1-6.5-4.7-4.5 6.5-1z" fill="#FFFFFF" />
      <rect x="148" y="284" width="140" height="84" rx="14" :fill="`url(#${g('brand')})`" />
      <path d="M148 352l34-30 26 22 22-16 58 40v0H148z" fill="#0B0B1F" opacity="0.25" />
      <circle cx="262" cy="306" r="10" fill="#FFFFFF" opacity="0.8" />
      <rect x="148" y="380" width="116" height="9" rx="4.5" class="fill-gray-200 dark:fill-gray-700" />
      <rect x="148" y="398" width="76" height="9" rx="4.5" class="fill-gray-200 dark:fill-gray-700" />
    </g>

    <!-- Story ring (front right): an abstract avatar, not a person -->
    <g :filter="`url(#${g('shadow')})`">
      <circle cx="420" cy="368" r="56" class="fill-white dark:fill-gray-900" />
      <circle cx="420" cy="368" r="52" fill="none" :stroke="`url(#${g('brand')})`" stroke-width="6" />
      <g :clip-path="`url(#${g('avatar')})`">
        <rect x="374" y="322" width="92" height="92" fill="#E8E6FF" />
        <circle cx="420" cy="356" r="17" fill="#A855F7" />
        <path d="M384 414c6-26 22-38 36-38s30 12 36 38z" fill="#6A00F4" />
      </g>
    </g>

    <!-- Heart reaction -->
    <g :filter="`url(#${g('shadow')})`">
      <circle cx="484" cy="262" r="34" fill="#FF4ED8" />
      <path
        d="M484 278c-15-10-22-17-22-26a11 11 0 0 1 22-3 11 11 0 0 1 22 3c0 9-7 16-22 26z"
        fill="#FFFFFF"
      />
    </g>

    <!-- Smile reaction -->
    <g :filter="`url(#${g('shadow')})`">
      <circle cx="150" cy="70" r="32" fill="#A855F7" />
      <circle cx="139" cy="64" r="4" fill="#FFFFFF" />
      <circle cx="161" cy="64" r="4" fill="#FFFFFF" />
      <path d="M134 77c8 12 24 12 32 0" fill="none" stroke="#FFFFFF" stroke-width="4" stroke-linecap="round" />
    </g>

    <!-- Chat bubble -->
    <g :filter="`url(#${g('shadow')})`">
      <path d="M40 190h70a16 16 0 0 1 16 16v22a16 16 0 0 1-16 16H70l-16 14v-14H40a16 16 0 0 1-16-16v-22a16 16 0 0 1 16-16z" class="fill-white dark:fill-gray-900" />
      <circle cx="56" cy="217" r="5" fill="#6A00F4" />
      <circle cx="75" cy="217" r="5" fill="#A855F7" />
      <circle cx="94" cy="217" r="5" fill="#FF4ED8" />
    </g>
  </svg>
</template>
