from typing import Protocol

from store_operator.ai_gateway.schemas import (
    ImageEditRequest,
    ImageGenerateRequest,
    ImageGenerateResponse,
    OCRRequest,
    OCRResponse,
    TextGenerateRequest,
    TextGenerateResponse,
    VisionInspectRequest,
    VisionInspectResponse,
)


class TextProvider(Protocol):
    async def generate(self, request: TextGenerateRequest) -> TextGenerateResponse: ...


class ImageProvider(Protocol):
    async def generate(self, request: ImageGenerateRequest) -> ImageGenerateResponse: ...

    async def edit(self, request: ImageEditRequest) -> ImageGenerateResponse: ...


class VisionProvider(Protocol):
    async def inspect(self, request: VisionInspectRequest) -> VisionInspectResponse: ...


class OCRProvider(Protocol):
    async def extract(self, request: OCRRequest) -> OCRResponse: ...
