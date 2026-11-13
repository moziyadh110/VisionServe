"""Florence-2 wrapper.

torch and transformers are imported inside functions, not at module level, so the
rest of the app (and the test suite) can import this file without the ML stack.
"""

from typing import Protocol

from PIL import Image

from app.schemas.inference import Task

# Florence-2 picks its task from a special prompt token.
TASK_PROMPTS = {
    Task.caption: "<CAPTION>",
    Task.detailed_caption: "<DETAILED_CAPTION>",
    Task.ocr: "<OCR>",
}


class ImageModel(Protocol):
    """Anything with predict() can serve requests; tests use a fake."""

    def predict(self, image: Image.Image, task: Task) -> str: ...


class Florence2Model:
    def __init__(self, model, processor, device: str, dtype, max_new_tokens: int):
        self.model = model
        self.processor = processor
        self.device = device
        self.dtype = dtype
        self.max_new_tokens = max_new_tokens

    @classmethod
    def load(cls, model_id: str, device: str, max_new_tokens: int) -> "Florence2Model":
        """Load weights once. Slow (seconds), so it runs off the event loop at startup."""
        from unittest.mock import patch

        import torch
        from transformers import AutoModelForCausalLM, AutoProcessor
        from transformers.dynamic_module_utils import get_imports

        if device == "cuda" and not torch.cuda.is_available():
            device = "cpu"
        # FP16 halves memory and is faster on GPU; CPUs don't do FP16 well.
        dtype = torch.float16 if device == "cuda" else torch.float32

        # Florence-2's remote code lists flash_attn as an import even though it
        # doesn't need it; drop it so loading works without that package.
        def _imports_without_flash_attn(filename):
            return [i for i in get_imports(filename) if i != "flash_attn"]

        with patch("transformers.dynamic_module_utils.get_imports", _imports_without_flash_attn):
            model = AutoModelForCausalLM.from_pretrained(
                model_id,
                torch_dtype=dtype,
                trust_remote_code=True,
                attn_implementation="eager",
            )
        processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
        model.to(device).eval()
        return cls(model, processor, device, dtype, max_new_tokens)

    def predict(self, image: Image.Image, task: Task) -> str:
        """Blocking GPU call. Must only run in the GPU worker thread, never on the event loop."""
        import torch

        prompt = TASK_PROMPTS[task]
        inputs = self.processor(text=prompt, images=image, return_tensors="pt")
        with torch.inference_mode():
            generated = self.model.generate(
                input_ids=inputs["input_ids"].to(self.device),
                pixel_values=inputs["pixel_values"].to(self.device, self.dtype),
                max_new_tokens=self.max_new_tokens,
                num_beams=3,
                do_sample=False,
            )
        raw = self.processor.batch_decode(generated, skip_special_tokens=False)[0]
        parsed = self.processor.post_process_generation(
            raw, task=prompt, image_size=(image.width, image.height)
        )
        return str(parsed[prompt]).strip()
