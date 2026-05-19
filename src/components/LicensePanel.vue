<script setup>
import { computed, onMounted, ref } from 'vue';
import { getLicenseDeviceFingerprints, getLicenseStatus, importLicense } from '../lib/api.js';

const licenseStatus = ref(null);
const deviceFingerprints = ref([]);
const isRefreshing = ref(false);
const isImporting = ref(false);
const importMessage = ref('');
const licenseContent = ref('');

const statusTone = computed(() => (
  licenseStatus.value?.valid ? 'license-status-valid' : 'license-status-invalid'
));

const expiresLabel = computed(() => {
  const value = licenseStatus.value?.expires_at;
  if (!value) {
    if (licenseStatus.value?.valid) {
      return '永久';
    }
    return '未写过期时间';
  }

  return new Date(value).toLocaleString('zh-CN');
});

const primaryDeviceFingerprint = computed(() => deviceFingerprints.value[0] ?? '');

async function refreshStatus() {
  isRefreshing.value = true;
  importMessage.value = '';

  try {
    licenseStatus.value = await getLicenseStatus();
    const devicePayload = await getLicenseDeviceFingerprints();
    deviceFingerprints.value = Array.isArray(devicePayload?.fingerprints)
      ? devicePayload.fingerprints
      : [];
  } catch (error) {
    importMessage.value =
      error instanceof Error ? error.message : '许可证状态读取失败';
  } finally {
    isRefreshing.value = false;
  }
}

async function submitLicense() {
  if (!licenseContent.value.trim()) {
    importMessage.value = '先把许可证内容贴进来';
    return;
  }

  isImporting.value = true;
  importMessage.value = '';

  try {
    licenseStatus.value = await importLicense(licenseContent.value.trim());
    importMessage.value = licenseStatus.value.valid ? '许可证已导入' : licenseStatus.value.reason;
    if (licenseStatus.value.valid) {
      licenseContent.value = '';
    }
  } catch (error) {
    importMessage.value =
      error instanceof Error ? error.message : '许可证导入失败';
  } finally {
    isImporting.value = false;
  }
}

async function copyDeviceFingerprint() {
  if (!primaryDeviceFingerprint.value) {
    importMessage.value = '当前没有可复制的设备码';
    return;
  }

  try {
    await navigator.clipboard.writeText(primaryDeviceFingerprint.value);
    importMessage.value = '设备码已复制';
  } catch {
    importMessage.value = '设备码复制失败，可以手动选中复制';
  }
}

onMounted(() => {
  void refreshStatus();
});
</script>

<template>
  <section class="panel license-panel">
    <header class="license-head">
      <div>
        <p class="license-kicker">许可证</p>
        <h3>{{ licenseStatus?.valid ? '已激活' : '未激活' }}</h3>
      </div>

      <button
        :disabled="isRefreshing"
        class="ghost-button"
        type="button"
        @click="refreshStatus"
      >
        {{ isRefreshing ? '刷新中…' : '刷新状态' }}
      </button>
    </header>

    <div
      v-if="licenseStatus"
      :class="['license-status', statusTone]"
    >
      <strong>{{ licenseStatus.reason }}</strong>
      <span>过期时间：{{ expiresLabel }}</span>
    </div>

    <div
      v-if="primaryDeviceFingerprint"
      class="device-code"
    >
      <span>当前设备码</span>
      <code>{{ primaryDeviceFingerprint }}</code>
      <button
        class="ghost-button"
        type="button"
        @click="copyDeviceFingerprint"
      >
        复制设备码
      </button>
    </div>

    <label class="license-input">
      <span>导入许可证</span>
      <textarea
        v-model="licenseContent"
        rows="6"
        placeholder='粘贴签名许可证，例如 {"algorithm":"ed25519","payload":{"licensee":"张三","expires_at":"2026-12-31T00:00:00Z"},"signature":"..."} 或 {"algorithm":"ed25519","payload":{"licensee":"张三","permanent":true},"signature":"..."}'
      />
    </label>

    <p
      v-if="importMessage"
      class="message"
    >
      {{ importMessage }}
    </p>

    <button
      :disabled="isImporting"
      type="button"
      @click="submitLicense"
    >
      {{ isImporting ? '导入中…' : '导入许可证' }}
    </button>
  </section>
</template>

<style scoped>
.panel {
  border-radius: 18px;
  background: #ffffff;
  border: 1px solid #dce6f4;
  overflow: hidden;
}

.license-panel {
  display: grid;
  gap: 14px;
  padding: 16px;
}

.license-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.license-kicker {
  margin: 0 0 8px;
  font-size: 11px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: #6e7781;
}

.license-head h3 {
  margin: 0;
  font-size: 18px;
  color: #1f2328;
}

.license-status {
  display: grid;
  gap: 4px;
  border-radius: 12px;
  padding: 14px;
  border: 1px solid #d0d7de;
}

.license-status strong {
  font-size: 14px;
  color: #1f2328;
}

.license-status span {
  font-size: 13px;
  color: #57606a;
}

.license-status-valid {
  background: #eefbf3;
  border-color: #b9e6c8;
}

.license-status-invalid {
  background: #fff5f3;
  border-color: #f0c3bc;
}

.device-code {
  display: grid;
  gap: 8px;
  border: 1px solid #d0d7de;
  border-radius: 12px;
  padding: 12px;
}

.device-code span {
  color: #57606a;
  font-size: 13px;
}

.device-code code {
  color: #1f2328;
  font-size: 12px;
  line-height: 1.5;
  word-break: break-all;
}

.license-input {
  display: grid;
  gap: 8px;
}

.license-input > span {
  color: #57606a;
  font-size: 13px;
}

textarea {
  width: 100%;
  border: 1px solid #d0d7de;
  background: #ffffff;
  border-radius: 14px;
  padding: 12px 14px;
  color: #1f2328;
  font-size: 13px;
  resize: vertical;
  min-height: 120px;
}

.ghost-button {
  border: 1px solid #d0d7de;
  background: #ffffff;
  border-radius: 999px;
  padding: 9px 13px;
  color: #1f2328;
  font-size: 13px;
}

button {
  justify-self: start;
  border: none;
  background: #1d4ed8;
  color: #ffffff;
  border-radius: 999px;
  padding: 11px 15px;
  font-size: 14px;
}

button:disabled {
  opacity: 0.6;
}

.message {
  margin: 0;
  color: #57606a;
  font-size: 13px;
}
</style>
