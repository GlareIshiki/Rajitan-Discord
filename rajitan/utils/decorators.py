import asyncio
import functools
from typing import Any, Callable, Optional, Union, Type
from rajitan.utils.logger import get_logger


def handle_async_errors(
    operation_name: str = None,
    default_return: Any = None,
    log_errors: bool = True,
    reraise: Union[bool, tuple] = False
):
    """
    Decorator for standardized async error handling
    
    Args:
        operation_name: Description of the operation for logging
        default_return: Value to return on error
        log_errors: Whether to log errors
        reraise: Whether to reraise specific exceptions (True for all, tuple for specific types)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Get logger from the class instance or create a new one
            if args and hasattr(args[0], '__class__'):
                logger_name = args[0].__class__.__name__.lower()
            else:
                logger_name = func.__module__
            logger = get_logger(logger_name)
            
            op_name = operation_name or f"{func.__name__}"
            
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                if log_errors:
                    logger.error(f"Failed to {op_name}: {e}")
                
                # Check if we should reraise
                if reraise is True:
                    raise
                elif isinstance(reraise, tuple) and isinstance(e, reraise):
                    raise
                
                return default_return
        return wrapper
    return decorator


def handle_sync_errors(
    operation_name: str = None,
    default_return: Any = None,
    log_errors: bool = True,
    reraise: Union[bool, tuple] = False
):
    """
    Decorator for standardized sync error handling
    
    Args:
        operation_name: Description of the operation for logging
        default_return: Value to return on error
        log_errors: Whether to log errors
        reraise: Whether to reraise specific exceptions
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Get logger from the class instance or create a new one
            if args and hasattr(args[0], '__class__'):
                logger_name = args[0].__class__.__name__.lower()
            else:
                logger_name = func.__module__
            logger = get_logger(logger_name)
            
            op_name = operation_name or f"{func.__name__}"
            
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if log_errors:
                    logger.error(f"Failed to {op_name}: {e}")
                
                # Check if we should reraise
                if reraise is True:
                    raise
                elif isinstance(reraise, tuple) and isinstance(e, reraise):
                    raise
                
                return default_return
        return wrapper
    return decorator


def with_retries(max_retries: int = 3, delay: float = 1.0, exponential_backoff: bool = True):
    """
    Decorator to add retry logic to async functions
    
    Args:
        max_retries: Maximum number of retry attempts
        delay: Initial delay between retries in seconds
        exponential_backoff: Whether to use exponential backoff
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Get logger
            if args and hasattr(args[0], '__class__'):
                logger_name = args[0].__class__.__name__.lower()
            else:
                logger_name = func.__module__
            logger = get_logger(logger_name)
            
            last_exception = None
            current_delay = delay
            
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    
                    if attempt == max_retries:
                        logger.error(f"Function {func.__name__} failed after {max_retries} retries: {e}")
                        raise
                    
                    logger.warning(f"Function {func.__name__} failed (attempt {attempt + 1}/{max_retries + 1}): {e}")
                    
                    if attempt < max_retries:
                        await asyncio.sleep(current_delay)
                        if exponential_backoff:
                            current_delay *= 2
            
            # This should not be reached, but just in case
            raise last_exception
        return wrapper
    return decorator


def validate_params(**validators):
    """
    Decorator to validate function parameters
    
    Args:
        **validators: Dictionary of parameter_name: validation_function
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            # Get function signature
            import inspect
            sig = inspect.signature(func)
            bound_args = sig.bind(*args, **kwargs)
            bound_args.apply_defaults()
            
            # Validate parameters
            for param_name, validator in validators.items():
                if param_name in bound_args.arguments:
                    value = bound_args.arguments[param_name]
                    if not validator(value):
                        raise ValueError(f"Invalid value for parameter '{param_name}': {value}")
            
            return await func(*args, **kwargs)
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            # Get function signature
            import inspect
            sig = inspect.signature(func)
            bound_args = sig.bind(*args, **kwargs)
            bound_args.apply_defaults()
            
            # Validate parameters
            for param_name, validator in validators.items():
                if param_name in bound_args.arguments:
                    value = bound_args.arguments[param_name]
                    if not validator(value):
                        raise ValueError(f"Invalid value for parameter '{param_name}': {value}")
            
            return func(*args, **kwargs)
        
        # Return appropriate wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    return decorator


def log_function_calls(include_args: bool = False, include_result: bool = False):
    """
    Decorator to log function calls for debugging
    
    Args:
        include_args: Whether to include arguments in the log
        include_result: Whether to include the result in the log
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            # Get logger
            if args and hasattr(args[0], '__class__'):
                logger_name = args[0].__class__.__name__.lower()
            else:
                logger_name = func.__module__
            logger = get_logger(logger_name)
            
            # Log function call
            call_info = f"Calling {func.__name__}"
            if include_args and (args or kwargs):
                call_info += f" with args={args}, kwargs={kwargs}"
            logger.debug(call_info)
            
            # Execute function
            result = await func(*args, **kwargs)
            
            # Log result if requested
            if include_result:
                logger.debug(f"{func.__name__} returned: {result}")
            
            return result
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            # Get logger
            if args and hasattr(args[0], '__class__'):
                logger_name = args[0].__class__.__name__.lower()
            else:
                logger_name = func.__module__
            logger = get_logger(logger_name)
            
            # Log function call
            call_info = f"Calling {func.__name__}"
            if include_args and (args or kwargs):
                call_info += f" with args={args}, kwargs={kwargs}"
            logger.debug(call_info)
            
            # Execute function
            result = func(*args, **kwargs)
            
            # Log result if requested
            if include_result:
                logger.debug(f"{func.__name__} returned: {result}")
            
            return result
        
        # Return appropriate wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    return decorator