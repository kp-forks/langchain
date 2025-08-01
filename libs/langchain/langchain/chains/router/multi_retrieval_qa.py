"""Use a single chain to route an input to one of multiple retrieval qa chains."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional

from langchain_core.language_models import BaseLanguageModel
from langchain_core.prompts import PromptTemplate
from langchain_core.retrievers import BaseRetriever
from typing_extensions import override

from langchain.chains import ConversationChain
from langchain.chains.base import Chain
from langchain.chains.conversation.prompt import DEFAULT_TEMPLATE
from langchain.chains.retrieval_qa.base import BaseRetrievalQA, RetrievalQA
from langchain.chains.router.base import MultiRouteChain
from langchain.chains.router.llm_router import LLMRouterChain, RouterOutputParser
from langchain.chains.router.multi_retrieval_prompt import (
    MULTI_RETRIEVAL_ROUTER_TEMPLATE,
)


class MultiRetrievalQAChain(MultiRouteChain):
    """A multi-route chain that uses an LLM router chain to choose amongst retrieval
    qa chains."""

    router_chain: LLMRouterChain
    """Chain for deciding a destination chain and the input to it."""
    destination_chains: Mapping[str, BaseRetrievalQA]
    """Map of name to candidate chains that inputs can be routed to."""
    default_chain: Chain
    """Default chain to use when router doesn't map input to one of the destinations."""

    @property
    @override
    def output_keys(self) -> list[str]:
        return ["result"]

    @classmethod
    def from_retrievers(
        cls,
        llm: BaseLanguageModel,
        retriever_infos: list[dict[str, Any]],
        default_retriever: Optional[BaseRetriever] = None,
        default_prompt: Optional[PromptTemplate] = None,
        default_chain: Optional[Chain] = None,
        *,
        default_chain_llm: Optional[BaseLanguageModel] = None,
        **kwargs: Any,
    ) -> MultiRetrievalQAChain:
        """Create a multi retrieval qa chain from an LLM and a default chain.

        Args:
            llm: The language model to use.
            retriever_infos: Dictionaries containing retriever information.
            default_retriever: Optional default retriever to use if no default chain
                is provided.
            default_prompt: Optional prompt template to use for the default retriever.
            default_chain: Optional default chain to use when router doesn't map input
                to one of the destinations.
            default_chain_llm: Optional language model to use if no default chain and
                no default retriever are provided.
            **kwargs: Additional keyword arguments to pass to the chain.
        Returns:
            An instance of the multi retrieval qa chain.
        """
        if default_prompt and not default_retriever:
            msg = (
                "`default_retriever` must be specified if `default_prompt` is "
                "provided. Received only `default_prompt`."
            )
            raise ValueError(msg)
        destinations = [f"{r['name']}: {r['description']}" for r in retriever_infos]
        destinations_str = "\n".join(destinations)
        router_template = MULTI_RETRIEVAL_ROUTER_TEMPLATE.format(
            destinations=destinations_str,
        )
        router_prompt = PromptTemplate(
            template=router_template,
            input_variables=["input"],
            output_parser=RouterOutputParser(next_inputs_inner_key="query"),
        )
        router_chain = LLMRouterChain.from_llm(llm, router_prompt)
        destination_chains = {}
        for r_info in retriever_infos:
            prompt = r_info.get("prompt")
            retriever = r_info["retriever"]
            chain = RetrievalQA.from_llm(llm, prompt=prompt, retriever=retriever)
            name = r_info["name"]
            destination_chains[name] = chain
        if default_chain:
            _default_chain = default_chain
        elif default_retriever:
            _default_chain = RetrievalQA.from_llm(
                llm,
                prompt=default_prompt,
                retriever=default_retriever,
            )
        else:
            prompt_template = DEFAULT_TEMPLATE.replace("input", "query")
            prompt = PromptTemplate(
                template=prompt_template,
                input_variables=["history", "query"],
            )
            if default_chain_llm is None:
                msg = (
                    "conversation_llm must be provided if default_chain is not "
                    "specified. This API has been changed to avoid instantiating "
                    "default LLMs on behalf of users."
                    "You can provide a conversation LLM like so:\n"
                    "from langchain_openai import ChatOpenAI\n"
                    "llm = ChatOpenAI()"
                )
                raise NotImplementedError(msg)
            _default_chain = ConversationChain(
                llm=default_chain_llm,
                prompt=prompt,
                input_key="query",
                output_key="result",
            )
        return cls(
            router_chain=router_chain,
            destination_chains=destination_chains,
            default_chain=_default_chain,
            **kwargs,
        )
